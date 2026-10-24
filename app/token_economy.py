"""Remove transport/presentation noise, retaining complete prose for grounded quotes."""
import re
from .utils import sha256_text


def model_text(body):
    lines=[]
    for line in body.splitlines():
        # Image pixels are not sent to a text model; keep the original archived separately.
        if re.fullmatch(r'\s*!\[[^\]]*\]\(https?://[^\s)]+\)\s*',line):continue
        if re.fullmatch(r'\s*(?:来源[：:]\s*)?https?://\S+\s*',line):continue
        # Retain all non-URL prose verbatim; evidence remains locatable in the source.
        line=re.sub(r'https?://[^\s<>]+','',line).rstrip()
        if line.strip():lines.append(line)
    return '\n\n'.join(lines)


def analysis_hash(body):
    return sha256_text(model_text(body))
