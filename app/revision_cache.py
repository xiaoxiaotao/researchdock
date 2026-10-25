"""Bounded parsed archive cache; processing/AI state is always read live."""
from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from .frontmatter import split_frontmatter

_LIMIT = 16 * 1024 * 1024
_entries = OrderedDict()
_bytes = 0
_lock = RLock()


def revision_content(storage, relative_path):
    global _bytes
    path = storage.resolve_path(relative_path)
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    with _lock:
        cached = _entries.get(key)
        if cached is not None:
            _entries.move_to_end(key)
            return deepcopy(cached[0]), cached[1]
    text = storage.read_revision_text(relative_path)
    meta, body = split_frontmatter(text)
    weight = len(text.encode('utf-8')) * 3  # Allow for Python strings and parsed metadata.
    if weight <= _LIMIT:
        with _lock:
            # Remove superseded versions of the same file and account for races.
            for old in [k for k in _entries if k[0] == key[0]]:
                _bytes -= _entries.pop(old)[2]
            while _entries and _bytes + weight > _LIMIT:
                _, old = _entries.popitem(last=False)
                _bytes -= old[2]
            _entries[key] = (deepcopy(meta), body, weight)
            _bytes += weight
    return meta, body
