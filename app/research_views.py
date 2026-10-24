"""Persistent, local reading filters; links only target the reading page."""
from datetime import date, datetime, timedelta
from threading import RLock
from urllib.parse import urlencode
from .storage import read_json, atomic_write_json
from .utils import now_iso, ulid, TZ
from .industries import CATEGORIES

_LOCK = RLock()

def views(storage):
    return read_json(storage.path('catalog/research-views.json')) or []

def link(filters):
    return '/reading?' + urlencode({k: str(v).lower() if type(v) is bool else v for k,v in filters.items()})

def date_range(filters, today=None):
    days=filters.get('days',0)
    if type(days) is not int or days not in (0,7,30):raise ValueError('日期范围无效')
    if days:
        today=today or datetime.now(TZ).date()
        return (today-timedelta(days=days-1)).isoformat(),today.isoformat()
    return filters.get('start',''),filters.get('end','')

def matches(note,filters,today=None):
    start,end=date_range(filters,today)
    stamp=note.get('reading_day') or (note.get('published_at') or '')[:10]
    if (start or end) and (not stamp or stamp=='日期未知'):return False
    if start and stamp<start or end and stamp>end:return False
    if filters.get('industry') and filters['industry'] not in note.get('industries',[]):return False
    if filters.get('unread') and note.get('is_read'):return False
    if filters.get('starred') and not note.get('is_starred'):return False
    if filters.get('selected') and not note.get('is_selected'):return False
    import json
    text=json.dumps({k:note.get(k) for k in ('title','summary','industries','stocks','key_points','risks')},ensure_ascii=False)
    return not filters.get('q') or filters['q'].casefold() in text.casefold()

def unread_counts(notes,rows):
    # Counts are source documents, even when the reading view folds events.
    return [{**row,'unread_count':sum(not n.get('is_read') and matches(n,row['filters']) for n in notes)} for row in rows]

def save(storage, data):
    if not isinstance(data,dict):raise ValueError('视图参数无效')
    name=data.get('name');raw=data.get('filters')
    if not isinstance(name,str) or not 1<=len(name.strip())<=40:raise ValueError('视图名称需为1至40字')
    if not isinstance(raw,dict):raise ValueError('筛选条件无效')
    filters={}
    for key in ('q','industry','start','end'):
        value=raw.get(key,'')
        if not isinstance(value,str) or len(value)>200:raise ValueError('筛选条件无效')
        filters[key]=value.strip()
    if filters['industry'] and filters['industry'] not in (*CATEGORIES,'待分类'):raise ValueError('行业无效')
    for key in ('start','end'):
        if filters[key]:
            try:filters[key]=date.fromisoformat(filters[key]).isoformat()
            except ValueError:raise ValueError('日期无效') from None
    if filters['start'] and filters['end'] and filters['start']>filters['end']:raise ValueError('开始日期不能晚于结束日期')
    for key in ('unread','starred','selected','dedup'):
        value=raw.get(key,False)
        if type(value) is not bool:raise ValueError('阅读选项需为布尔值')
        filters[key]=value
    days=raw.get('days',0)
    date_range({'days':days})
    filters['days']=days
    if days:filters['start']=filters['end']=''
    with _LOCK:
        rows=views(storage)
        for row in rows:
            if row['name']==name.strip() and { 'days':0, **row['filters']}==filters:return row
        if len(rows)>=50:raise ValueError('最多保存50个视图，请先移除不再使用的视图')
        row={'id':'view_'+ulid(),'name':name.strip(),'filters':filters,'created_at':now_iso()}
        rows.append(row);atomic_write_json(storage.path('catalog/research-views.json'),rows)
        return row

def remove(storage,key):
    with _LOCK:
        rows=views(storage)
        if not any(r['id']==key for r in rows):raise ValueError('视图不存在')
        atomic_write_json(storage.path('catalog/research-views.json'),[r for r in rows if r['id']!=key])
