"""Deterministic mobile presentation and a credential-free collection heartbeat."""
import re
from .storage import read_json
from .utils import now_iso

PLACEHOLDERS={'「文件」','[文件]','【文件】','此主题仅含附件，附件清单已登记，原件请到知识星球查看。'}

def presentation(row,body,attachments,summary):
    text=body.strip();title=row['title'].strip()
    prose=re.sub(r'!\[[^]]*\]\([^\n]*?\)','',text).strip()
    only=not prose or prose in PLACEHOLDERS or title in PLACEHOLDERS or bool(attachments) and prose==title
    kind='attachment_only' if only else 'brief' if len(prose)<80 else 'note'
    display=title
    if title in PLACEHOLDERS and attachments:
        display=attachments[0]['name']+(f' 等 {len(attachments)} 项附件' if len(attachments)>1 else '')
    points=[v.strip() for v in summary.get('key_points',[]) if isinstance(v,str) and v.strip()]
    risks=[v.strip() for v in summary.get('risks',[]) if isinstance(v,str) and v.strip()]
    return dict(key_points=points,risks=risks,analysis_revision=row['current_revision'] if summary else 0,
                first_imported_at=row['first_imported_at'] or '',body_chars=len(text),content_kind=kind,display_title=display)

def source_health(storage):
    settings=read_json(storage.path('catalog/research-settings.json')) or {}
    polls=read_json(storage.path('jobs/source-poll.json')) or {};sources=[]
    for path in sorted(storage.path('catalog/sources').glob('zsxq_*.json')):
        d=read_json(path) or {};state=d.get('status','unknown')
        if state not in ('queued','running','failed','interrupted','succeeded','partial','idle'):state='unknown'
        sources.append(dict(name=str(d.get('name') or d.get('group_name') or '知识星球')[:200],status=state,
                            last_success_at=d.get('last_synced_at') or '',last_attempt_at=polls.get(str(d.get('group_id')),'') or '',unavailable_count=max(0,int(d.get('window_unavailable_count') or 0))))
    minutes=settings.get('poll_minutes',5)
    return dict(reported_at=now_iso(),poll_enabled=bool(settings.get('poll_enabled',False)),
                poll_minutes=minutes if type(minutes)is int and minutes in (5,10,15,30,60) else 5,sources=sources)
