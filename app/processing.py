"""Read-only processing inventory; source files never imply parsed content."""
from collections import Counter
from . import index
from .frontmatter import split_frontmatter
from .storage import read_json


def attachment_only(body):
    return not body.strip() or body.strip() in {'「文件」','[文件]','【文件】'} or body.startswith('此主题仅含附件')


def inventory(pipeline, research=None):
    with index.connect(pipeline.cfg.db_path) as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM documents ORDER BY imported_at DESC, document_id DESC')]
    result=[]
    failures={e.get('document_id') for e in (research.state().get('errors',[]) if research else [])}
    model=research.settings()['model'] if research else None
    for row in rows:
        manifest=pipeline.storage.read_manifest(row['document_id']) or {}
        rev=next((r for r in manifest.get('revisions',[]) if r['revision']==row['current_revision']),None)
        if not rev: continue
        meta,body=split_frontmatter(pipeline.storage.read_revision_text(rev['archive_path']))
        files=meta.get('source_attachments') or []
        summary=read_json(pipeline.storage.path(f"derived/summaries/{row['document_id']}.json")) or {}
        ready=summary.get('revision')==row['current_revision'] and (not model or summary.get('model')==model)
        state='attachment' if files and attachment_only(body) else 'insufficient' if attachment_only(body) else 'complete' if ready else 'failed' if row['document_id'] in failures else 'pending'
        row.update(processing_state=state,source_attachments=files,body=body,meta=meta)
        result.append(row)
    return result,dict(Counter(r['processing_state'] for r in result))
