"""Local-only homepage collection status. No remote calls or model inference."""
from datetime import datetime
from .mobile_editorial import source_health
from .utils import parse_iso, TZ

_NAMES={'queued':'等待采集','running':'正在采集','failed':'采集失败','interrupted':'采集中断','succeeded':'采集完成','partial':'部分待补','idle':'尚未采集','unknown':'状态未知'}

def collection_status(storage, now=None):
    health=source_health(storage)
    now=now or datetime.now(TZ)
    sources=[]
    for source in health['sources']:
        entry=dict(source,label=_NAMES[source['status']],delayed=False)
        stamp=parse_iso(source['last_success_at'])
        if source['status']=='succeeded' and not stamp:
            entry['delayed']=True
            entry['label']='暂无成功采集时间'
        if source['status']=='succeeded' and health['poll_enabled'] and stamp:
            entry['delayed']=(now-stamp).total_seconds()>(health['poll_minutes']+3)*60
            if entry['delayed']:entry['label']='更新延迟'
        sources.append(entry)
    warning=any(s['status'] in ('failed','interrupted','partial','unknown') or s['delayed'] for s in sources)
    label='请添加信源' if not sources else '采集需要检查' if warning else '自动采集已关闭' if not health['poll_enabled'] else '正在采集' if any(s['status'] in ('running','queued') for s in sources) else '采集状态正常' if all(s['status']=='succeeded' for s in sources) else '尚未完成首次采集'
    return dict(health,sources=sources,warning=warning,label=label)
