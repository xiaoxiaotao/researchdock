"""Local company coverage view, with source-document reading counts."""
from datetime import datetime
from .utils import parse_iso,TZ

def directory(companies,states,followed,q='',industry='',scope='all',sort='recent',page=1,size=24):
    followed=set(followed);rows=[]
    for company in companies:
        company=dict(company)
        ids=set(company.get('document_ids',[]))
        members={company['stock_id'],*company.get('member_ids',[])}
        row={**company,'is_followed':bool(members & followed),'unread_count':sum(not states.get(key,{}).get('read',False) for key in ids)}
        text=' '.join(str(company.get(k) or '') for k in ('name','code','catalog_code'))+' '+str((company.get('security') or {}).get('pinyin') or '')
        if q and q.casefold() not in text.casefold():continue
        if industry and industry not in company.get('industries',[]):continue
        if scope=='followed' and not row['is_followed']:continue
        if scope=='unread' and not row['unread_count']:continue
        rows.append(row)
    def moment(row):return parse_iso(row.get('last_at')) or datetime.min.replace(tzinfo=TZ)
    if sort=='recent':rows.sort(key=lambda r:(moment(r),r['stock_id']),reverse=True)
    elif sort=='coverage':rows.sort(key=lambda r:(-r.get('doc_count',0),r.get('name') or r.get('code') or '',r['stock_id']))
    else:rows.sort(key=lambda r:(r.get('name') or r.get('code') or '',r['stock_id']))
    documents={key for r in rows for key in r.get('document_ids',[])}
    stats={'companies':len(rows),'documents':len(documents),'unread':sum(not states.get(key,{}).get('read',False) for key in documents),'followed':sum(r['is_followed'] for r in rows)}
    pages=max(1,(len(rows)+size-1)//size);page=min(max(1,page),pages)
    return {'rows':rows[(page-1)*size:page*size],'stats':stats,'page':page,'pages':pages}
