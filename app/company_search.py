"""Literal keyword lookup in archived company research, without model inference."""
from datetime import date

def filter_entries(entries,bodies,query='',start='',end=''):
    query=query.strip()
    if len(query)>200:raise ValueError('关键词不能超过200字')
    for value in (start,end):
        if value:
            try:date.fromisoformat(value)
            except ValueError:raise ValueError('日期格式无效') from None
    if start and end and start>end:raise ValueError('开始日期不能晚于结束日期')
    rows=[]
    for entry in entries:
        from .utils import parse_iso,TZ
        stamp=parse_iso(entry.get('published_at'))
        day=stamp.astimezone(TZ).date().isoformat() if stamp else ''
        if (start or end) and not day:continue
        if start and day<start or end and day>end:continue
        body=bodies.get(entry['document_id'],'')
        matches=[]
        if query:
            # re.IGNORECASE preserves original offsets even for Unicode case folds.
            import re
            hits=list(re.finditer(re.escape(query),body,re.IGNORECASE))
            if not hits:continue
            for hit in hits[:3]:
                a,b=hit.span()
                matches.append({'before':body[max(0,a-100):a],'text':body[a:b],'after':body[b:b+150]})
        rows.append({**entry,'source_matches':matches,'source_match_count':len(hits) if query else 0})
    return rows


def source_focus(body,query,hit=1):
    """Recompute the requested occurrence inside the chosen immutable revision."""
    import re
    if not isinstance(query,str) or len(query)>200:raise ValueError('关键词不能超过200字')
    if type(hit) is not int or hit<1:raise ValueError('命中序号无效')
    query=query.strip()
    if not query:return {'query':'','total':0,'hit':0,'match':None}
    matches=list(re.finditer(re.escape(query),body,re.IGNORECASE))
    total=len(matches)
    if not total:return {'query':query,'total':0,'hit':0,'match':None}
    hit=min(hit,total);a,b=matches[hit-1].span()
    return {'query':query,'total':total,'hit':hit,'match':{'before':body[max(0,a-200):a],'text':body[a:b],'after':body[b:b+300]}}
