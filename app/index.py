"""SQLite 索引：schema、写入与查询。

定位（设计文档 6.2）：索引只是持久文件的运行视图。删除本库后，
`rebuild_from_files()` 能仅凭 manifests 与归档正文恢复资料与关联。
正文使用 FTS5 trigram；不足三个字符的查询用字面子串检索。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    document_id       TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    current_revision  INTEGER NOT NULL DEFAULT 1,
    content_type      TEXT NOT NULL DEFAULT 'other',
    source_platform   TEXT,
    source_space_id   TEXT,
    source_space_name TEXT,
    source_item_id    TEXT,
    source_url        TEXT,
    source_key        TEXT,
    author_name       TEXT,
    published_at      TEXT,
    date_precision    TEXT NOT NULL DEFAULT 'unknown',
    imported_at       TEXT NOT NULL,
    first_imported_at TEXT NOT NULL,
    body_chars        INTEGER NOT NULL DEFAULT 0,
    excerpt           TEXT,
    deleted_at        TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_source_key
    ON documents(source_key) WHERE source_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_documents_imported ON documents(imported_at DESC);
CREATE INDEX IF NOT EXISTS ix_documents_published ON documents(published_at DESC);
CREATE INDEX IF NOT EXISTS ix_documents_type ON documents(content_type);

CREATE TABLE IF NOT EXISTS document_revisions (
    document_id  TEXT NOT NULL,
    revision     INTEGER NOT NULL,
    archive_path TEXT NOT NULL,
    body_hash    TEXT NOT NULL,
    file_hash    TEXT NOT NULL,
    imported_at  TEXT NOT NULL,
    body_chars   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (document_id, revision)
);

CREATE TABLE IF NOT EXISTS stocks (
    stock_id     TEXT PRIMARY KEY,
    market       TEXT NOT NULL DEFAULT 'CN',
    exchange     TEXT,
    code         TEXT NOT NULL,
    name         TEXT,
    aliases_json TEXT
);

CREATE TABLE IF NOT EXISTS document_stocks (
    document_id TEXT NOT NULL,
    stock_id    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'confirmed',
    method      TEXT NOT NULL DEFAULT 'export',
    PRIMARY KEY (document_id, stock_id, method)
);
CREATE INDEX IF NOT EXISTS ix_doc_stocks_stock ON document_stocks(stock_id);

CREATE VIRTUAL TABLE IF NOT EXISTS document_search USING fts5(
    document_id UNINDEXED, title, body, tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS document_pages (
    document_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (document_id, revision, page_number)
);

CREATE TABLE IF NOT EXISTS import_batches (
    batch_id      TEXT PRIMARY KEY,
    file_name     TEXT NOT NULL,
    file_hash     TEXT NOT NULL,
    file_format   TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    total         INTEGER NOT NULL DEFAULT 0,
    created       INTEGER NOT NULL DEFAULT 0,
    updated       INTEGER NOT NULL DEFAULT 0,
    duplicated    INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'running'
);
CREATE INDEX IF NOT EXISTS ix_batches_hash ON import_batches(file_hash);

CREATE TABLE IF NOT EXISTS import_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    TEXT NOT NULL,
    line_no     INTEGER,
    status      TEXT NOT NULL,
    document_id TEXT,
    revision    INTEGER,
    title       TEXT,
    message     TEXT
);
CREATE INDEX IF NOT EXISTS ix_results_batch ON import_results(batch_id);
"""


@contextmanager
def connect(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(db_path: Path) -> None:
    with connect(db_path) as conn:
        version = conn.execute("SELECT name FROM sqlite_master WHERE name='meta'").fetchone()
        if version:
            saved = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if saved and int(saved[0]) > SCHEMA_VERSION:
                raise RuntimeError("索引版本高于程序版本，请升级程序")
        conn.executescript(SCHEMA_SQL)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
        for name in ("institution", "report_period"):
            if name not in columns:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {name} TEXT")
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )


# ---------- 写入 ----------

def upsert_document(conn: sqlite3.Connection, doc: dict, revision: dict) -> None:
    conn.execute(
        """
        INSERT INTO documents (
            document_id, title, current_revision, content_type, source_platform,
            source_space_id, source_space_name, source_item_id, source_url, source_key,
            author_name, published_at, date_precision, imported_at, first_imported_at,
            body_chars, excerpt, deleted_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(document_id) DO UPDATE SET
            title=excluded.title,
            current_revision=excluded.current_revision,
            content_type=excluded.content_type,
            source_platform=excluded.source_platform,
            source_space_id=excluded.source_space_id,
            source_space_name=excluded.source_space_name,
            source_item_id=excluded.source_item_id,
            source_url=excluded.source_url,
            source_key=excluded.source_key,
            author_name=excluded.author_name,
            published_at=excluded.published_at,
            date_precision=excluded.date_precision,
            imported_at=excluded.imported_at,
            body_chars=excluded.body_chars,
            excerpt=excluded.excerpt,
            deleted_at=excluded.deleted_at
        """,
        (
            doc["document_id"], doc["title"], doc["current_revision"], doc["content_type"],
            doc.get("source_platform"), doc.get("source_space_id"), doc.get("source_space_name"),
            doc.get("source_item_id"), doc.get("source_url"), doc.get("source_key"),
            doc.get("author_name"), doc.get("published_at"), doc.get("date_precision", "unknown"),
            doc["imported_at"], doc["first_imported_at"], doc.get("body_chars", 0),
            doc.get("excerpt"), doc.get("deleted_at"),
        ),
    )
    conn.execute("UPDATE documents SET institution=?, report_period=? WHERE document_id=?",
                 (doc.get("institution"), doc.get("report_period"), doc["document_id"]))
    conn.execute(
        """
        INSERT INTO document_revisions
            (document_id, revision, archive_path, body_hash, file_hash, imported_at, body_chars)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(document_id, revision) DO UPDATE SET
            archive_path=excluded.archive_path,
            body_hash=excluded.body_hash,
            file_hash=excluded.file_hash
        """,
        (
            revision["document_id"], revision["revision"], revision["archive_path"],
            revision["body_hash"], revision["file_hash"], revision["imported_at"],
            revision.get("body_chars", 0),
        ),
    )


def upsert_stock(conn: sqlite3.Connection, stock_id: str, code: str, name: str,
                 market: str = "CN", exchange: str = "", aliases: list[str] | None = None) -> None:
    conn.execute(
        """
        INSERT INTO stocks(stock_id, market, exchange, code, name, aliases_json)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(stock_id) DO UPDATE SET
            name=COALESCE(NULLIF(excluded.name,''), stocks.name),
            exchange=COALESCE(NULLIF(excluded.exchange,''), stocks.exchange),
            aliases_json=COALESCE(excluded.aliases_json, stocks.aliases_json)
        """,
        (stock_id, market, exchange, code, name, None if aliases is None else _json(aliases)),
    )


def link_document_stock(conn: sqlite3.Connection, document_id: str, stock_id: str,
                        method: str = "export", status: str = "confirmed") -> None:
    conn.execute(
        """
        INSERT INTO document_stocks(document_id, stock_id, status, method)
        VALUES (?,?,?,?)
        ON CONFLICT(document_id, stock_id, method) DO UPDATE SET status=excluded.status
        """,
        (document_id, stock_id, status, method),
    )


def _json(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


# ---------- 查询 ----------

def get_document(conn: sqlite3.Connection, document_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM documents WHERE document_id=?", (document_id,)
    ).fetchone()


def get_revisions(conn: sqlite3.Connection, document_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM document_revisions WHERE document_id=? ORDER BY revision DESC",
        (document_id,),
    ).fetchall()


def list_documents(conn: sqlite3.Connection, *, limit: int = 30, offset: int = 0,
                   date_field: str = "imported_at", start: str | None = None,
                   end: str | None = None, content_type: str | None = None,
                   platform: str | None = None, stock_id: str | None = None,
                   source_space_id: str | None = None,
                   q: str | None = None, include_deleted: bool = False,
                   order: str | None = None) -> tuple[list[sqlite3.Row], int]:
    where = ["1=1"]
    params: list = []
    if not include_deleted:
        where.append("d.deleted_at IS NULL")
    if date_field not in {"imported_at", "first_imported_at", "published_at"}:
        date_field = "imported_at"
    if start:
        where.append(f"d.{date_field} >= ?")
        params.append(start)
    if end:
        where.append(f"d.{date_field} < ?")
        params.append(end)
    if content_type:
        where.append("d.content_type = ?")
        params.append(content_type)
    if platform:
        where.append("d.source_platform = ?")
        params.append(platform)
    if source_space_id:
        where.append("d.source_space_id = ?")
        params.append(source_space_id)
    if stock_id:
        where.append("EXISTS (SELECT 1 FROM document_stocks s WHERE s.document_id=d.document_id AND s.stock_id=?)")
        params.append(stock_id)
    q = (q or "").strip()
    if q:
        if len(q) >= 3:
            text_condition = "d.document_id IN (SELECT document_id FROM document_search WHERE document_search MATCH ?)"
            text_params = ['"' + q.replace('"', '""') + '"']
        else:
            text_condition = "d.document_id IN (SELECT document_id FROM document_search WHERE instr(lower(title), lower(?))>0 OR instr(lower(body), lower(?))>0)"
            text_params = [q, q]
        where.append(f"""({text_condition}
            OR instr(lower(COALESCE(d.institution,'')),lower(?))>0
            OR EXISTS (SELECT 1 FROM document_stocks ds JOIN stocks st ON st.stock_id=ds.stock_id
                WHERE ds.document_id=d.document_id AND
                (instr(lower(st.code),lower(?))>0 OR instr(lower(COALESCE(st.name,'')),lower(?))>0
                OR instr(lower(COALESCE(st.aliases_json,'')),lower(?))>0)))""")
        params.extend([*text_params, q, q, q, q])

    where_sql = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM documents d WHERE {where_sql}", params).fetchone()[0]
    order_sql = order or f"d.{date_field} DESC, d.document_id DESC"
    rows = conn.execute(
        f"SELECT d.* FROM documents d WHERE {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    if not q:
        return rows, total
    results = []
    for row in rows:
        item = dict(row)
        match = conn.execute(
            "SELECT page_number, text FROM document_pages WHERE document_id=? AND revision=? "
            "AND instr(lower(text),lower(?))>0 ORDER BY page_number LIMIT 1",
            (row["document_id"], row["current_revision"], q),
        ).fetchone()
        text_row = conn.execute("SELECT body FROM document_search WHERE document_id=?",
                                (row["document_id"],)).fetchone()
        body = match["text"] if match else (text_row[0] if text_row else row["excerpt"] or "")
        pos = body.lower().find(q.lower())
        start_at = max(0, pos - 55)
        item["search_excerpt"] = ("…" if start_at else "") + body[start_at:start_at + 200] + ("…" if len(body) > start_at + 200 else "")
        item["search_page"] = match["page_number"] if match else None
        results.append(item)
    return results, total


def replace_search(conn, document_id: str, title: str, body: str) -> None:
    previous = conn.execute("SELECT title, body FROM document_search WHERE document_id=?", (document_id,)).fetchone()
    if previous and tuple(previous) == (title, body):
        return
    conn.execute("DELETE FROM document_search WHERE document_id=?", (document_id,))
    conn.execute("INSERT INTO document_search(document_id,title,body) VALUES (?,?,?)",
                 (document_id, title, body))


def replace_pages(conn, document_id: str, revision: int, pages: list[dict]) -> None:
    conn.execute("DELETE FROM document_pages WHERE document_id=? AND revision=?", (document_id, revision))
    conn.executemany("INSERT INTO document_pages(document_id,revision,page_number,text) VALUES (?,?,?,?)",
                     [(document_id, revision, p["number"], p["text"]) for p in pages])


def documents_for_stock(conn: sqlite3.Connection, stock_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT d.* FROM documents d
        JOIN document_stocks s ON s.document_id = d.document_id
        WHERE s.stock_id = ? AND d.deleted_at IS NULL
        ORDER BY COALESCE(d.published_at, d.imported_at) DESC
        """,
        (stock_id,),
    ).fetchall()


def stocks_of_document(conn: sqlite3.Connection, document_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT st.*, ds.method, ds.status FROM document_stocks ds
        JOIN stocks st ON st.stock_id = ds.stock_id
        WHERE ds.document_id = ?
        ORDER BY st.code
        """,
        (document_id,),
    ).fetchall()


def list_stocks(conn: sqlite3.Connection, q: str | None = None) -> list[sqlite3.Row]:
    sql = """
        SELECT s.*, COUNT(d.document_id) AS doc_count,
               MAX(COALESCE(d.published_at, d.imported_at)) AS last_at
        FROM stocks s
        LEFT JOIN document_stocks ds ON ds.stock_id = s.stock_id
        LEFT JOIN documents d ON d.document_id = ds.document_id AND d.deleted_at IS NULL
    """
    params: list = []
    if q:
        sql += " WHERE s.name LIKE ? OR s.code LIKE ? OR s.aliases_json LIKE ?"
        like = f"%{q}%"
        params = [like, like, like]
    sql += " GROUP BY s.stock_id ORDER BY doc_count DESC, s.code"
    return conn.execute(sql, params).fetchall()


def get_stock(conn: sqlite3.Connection, stock_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM stocks WHERE stock_id=?", (stock_id,)).fetchone()


def stats(conn: sqlite3.Connection, today_prefix: str) -> dict:
    def one(sql: str, params=()) -> int:
        row = conn.execute(sql, params).fetchone()
        return int(row[0] or 0) if row else 0

    base = "FROM documents WHERE deleted_at IS NULL"
    counts=conn.execute(f"""SELECT COUNT(*) AS total,
        COALESCE(SUM(imported_at LIKE ?),0) AS imported_today,
        COALESCE(SUM(first_imported_at LIKE ?),0) AS first_imported_today,
        COALESCE(SUM(published_at LIKE ?),0) AS published_today,
        COALESCE(SUM(published_at IS NULL),0) AS unknown_date {base}""",
        (f"{today_prefix}%",)*3).fetchone()
    return {
        **dict(counts),
        "revisions": one("SELECT COUNT(*) FROM document_revisions"),
        "stocks": one("SELECT COUNT(*) FROM stocks"),
        "by_type": {
            row["content_type"]: row["n"]
            for row in conn.execute(
                f"SELECT content_type, COUNT(*) AS n {base} GROUP BY content_type ORDER BY n DESC"
            ).fetchall()
        },
        "by_platform": {
            (row["source_platform"] or "未知来源"): row["n"]
            for row in conn.execute(
                f"SELECT source_platform, COUNT(*) AS n {base} GROUP BY source_platform ORDER BY n DESC"
            ).fetchall()
        },
    }


def recent_batches(conn: sqlite3.Connection, limit: int = 5) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM import_batches ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()


def recent_results(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM import_results ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
