"""First-party public discovery and a local bridge for institution research exports.
Public discovery stores titles and original links, not restricted research bodies.
"""
import json,re,threading
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit,urlunsplit
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
import httpx
from .storage import read_json,atomic_write_json,atomic_write_text
from .utils import now_iso,sha256_text,ulid,parse_iso

PROVIDERS={
 'bloomberg':{'name':'彭博 Bloomberg','home':'https://professional.bloomberg.com/support/api-library/','domains':['bloomberg.com','bloomberglp.com','assets.bbhub.io'],'public_url':'https://www.bloomberg.com/feeds/markets/news.rss','mode':'rss','description':'公开市场新闻索引；终端／企业数据与研报访问需对应授权'},
 'goldman_sachs':{'name':'高盛 Goldman Sachs','home':'https://marquee.gs.com/welcome/our-platform/data-services','domains':['goldmansachs.com','gs.com'],'public_url':'https://www.goldmansachs.com/insights','mode':'html','pattern':r'^/insights/articles/[^/]+$','description':'公开Insights文章索引；Marquee数据权限不等同于完整研报权限'},
 'morgan_stanley':{'name':'摩根士丹利 Morgan Stanley','home':'https://www.morganstanley.com/what-we-do/research/','domains':['morganstanley.com'],'public_url':'https://www.morganstanley.com/insights','mode':'html','pattern':r'^/insights/articles/[^/]+$','description':'公开Insights文章索引；完整研究报告需研究平台授权'},
 'jpmorgan':{'name':'摩根大通 J.P. Morgan','home':'https://www.jpmorgan.com/markets','domains':['jpmorgan.com'],'description':'Markets研究平台／DataQuery需核对具体数据与研报权限'},
 'ubs':{'name':'瑞银 UBS','home':'https://www.ubs.com/global/en/investment-bank/insights-and-data/global-research.html','domains':['ubs.com'],'description':'Global Research研究平台；可导入已有研究导出结果'},
 'citi':{'name':'花旗 Citi','home':'https://www.citigroup.com/global/insights/research','domains':['citigroup.com','citivelocity.com','citi.com'],'public_url':'https://www.citigroup.com/global/insights/research','mode':'html','pattern':r'^/global/insights/[^/]+$','description':'公开研究观点索引；完整报告通常通过Citi Velocity访问'},
 'bofa':{'name':'美银 BofA','home':'https://business.bofa.com/en-us/content/global-research-about.html','domains':['bofa.com','baml.com'],'description':'Global Research授权研究；本地导入接口可用'},
 'deutsche_bank':{'name':'德意志银行 Deutsche Bank','home':'https://corporates.db.com/solutions/investment-bank-solutions/Research/index?language_id=1','domains':['db.com','dbresearch.com'],'description':'研究平台授权内容；本地导入接口可用'},
}
_LOCK=threading.RLock()

def provider(key):
    if key not in PROVIDERS:raise ValueError('机构无效')
    return PROVIDERS[key]

def checked_url(key,url):
    info=provider(key)
    if not isinstance(url,str) or len(url)>2000:raise ValueError('原文链接无效')
    try:p=urlsplit(url);port=p.port
    except ValueError:raise ValueError('原文链接无效') from None
    if p.scheme!='https' or p.username or p.password or port not in (None,443) or not any(p.hostname==d or (p.hostname or '').endswith('.'+d) for d in info['domains']):raise ValueError('仅支持对应机构的官方HTTPS原文链接')
    if p.query:raise ValueError('原文链接请使用不含登录凭据或签名参数的规范地址')
    return urlunsplit((p.scheme,p.netloc,p.path,'',''))

class Links(HTMLParser):
    def __init__(self):super().__init__();self.url=None;self.parts=[];self.links=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.url=dict(attrs).get('href');self.parts=[]
        if tag in ('script','style'):self.hidden+=1
    def handle_data(self,text):
        if self.url and not self.hidden:self.parts.append(text)
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
        if tag=='a' and self.url:self.links.append((self.url,' '.join(' '.join(self.parts).split())));self.url=None

def public_records(key,content):
    info=provider(key);rows=[]
    if info['mode']=='rss':
        root=ET.fromstring(content)
        for item in root.findall('./channel/item')[:40]:
            title=(item.findtext('title') or '').strip();url=item.findtext('link') or '';published=None
            if item.findtext('pubDate'):
                try:published=parsedate_to_datetime(item.findtext('pubDate')).isoformat()
                except (ValueError,TypeError):pass
            if title:rows.append({'title':title,'url':checked_url(key,url),'published_at':published,'coverage':'public_index'})
    else:
        parser=Links();parser.feed(content);seen=set()
        for href,title in parser.links:
            url=urljoin(info['public_url'],href)
            if not re.fullmatch(info['pattern'],urlsplit(url).path) or len(title)<20 or len(title)>500:continue
            try:url=checked_url(key,url)
            except ValueError:continue
            if url in seen or url==info['public_url']:continue
            seen.add(url);rows.append({'title':title[:250],'url':url,'published_at':None,'coverage':'public_index'})
            if len(rows)>=40:break
    if not rows:raise ValueError('公开页面未发现可用文章索引；保留此前数据，请查看官方入口')
    return rows

def import_reports(pipeline,key,rows):
    info=provider(key)
    if not isinstance(rows,list) or not 1<=len(rows)<=100:raise ValueError('每次需提交1至100条报告信息')
    records=[]
    for row in rows:
        if not isinstance(row,dict):raise ValueError('报告参数无效')
        title=row.get('title');body=row.get('text','');coverage=row.get('coverage','supplied_metadata')
        if not isinstance(title,str) or not 1<=len(title.strip())<=500:raise ValueError('报告标题无效')
        if not isinstance(body,str) or len(body)>200000:raise ValueError('报告正文过长或格式无效')
        if coverage not in ('public_index','supplied_metadata','supplied_text'):raise ValueError('内容范围无效')
        if body and coverage!='supplied_text':raise ValueError('正文导入须标注为supplied_text，索引不作为报告全文')
        if coverage=='supplied_text' and not body.strip():raise ValueError('正文不能为空')
        external=row.get('external_id')
        if external is not None and (not isinstance(external,str) or not 1<=len(external)<=200):raise ValueError('外部报告ID无效')
        url=checked_url(key,row.get('url',''));published=row.get('published_at') or None
        if published and (not isinstance(published,str) or not parse_iso(published)):raise ValueError('发布时间无效，未知时可留空')
        text=body.strip() if body else '仅收录机构公开标题或外部提供的报告信息，不含研报全文。\n\n'+title.strip()+'\n\n原文：'+url
        records.append({'schema_version':1,'title':title.strip(),'content_text':text,'content_type':'research_note' if coverage=='supplied_text' else 'news','source_platform':key,'source_space_id':key,'source_space_name':info['name'],'source_item_id':sha256_text(external or url),'source_url':url,'institution':info['name'],'published_at':published,'tags':['海外机构',{'public_index':'公开索引（非全文）','supplied_metadata':'外部报告信息（非全文）','supplied_text':'外部提供正文'}[coverage]]})
    path=pipeline.storage.path(f'sources/international/{key}/{ulid()}.jsonl')
    atomic_write_text(path,'\n'.join(json.dumps(r,ensure_ascii=False) for r in records)+'\n')
    report=pipeline.import_file(path)
    if report.failed:raise ValueError('部分报告导入失败，请查看导入记录；已成功的条目保留')
    return {field:getattr(report,field) for field in ('created','updated','duplicated','failed')}

def states(storage):return read_json(storage.path('catalog/international-sources.json')) or {}

def sync_public(pipeline,key,transport=None):
    info=provider(key)
    if not info.get('public_url'):raise ValueError('该机构尚无已实现的公开采集适配器，可通过报告导入接口接入')
    with _LOCK:
        path=pipeline.storage.path('catalog/international-sources.json');all_states=states(pipeline.storage)
        try:
            # Known official URLs only; redirects must remain inside the institution.
            url=info['public_url']
            with httpx.Client(timeout=30,transport=transport,follow_redirects=False) as client:
                for _ in range(4):
                    with client.stream('GET',url) as response:
                        if response.is_redirect:
                            url=checked_url(key,urljoin(url,response.headers.get('location','')));continue
                        response.raise_for_status();chunks=[];size=0
                        for part in response.iter_bytes():
                            size+=len(part)
                            if size>8*1024*1024:raise ValueError('公开页面过大，已停止采集')
                            chunks.append(part)
                        content=b''.join(chunks).decode('utf-8-sig');break
                else:raise ValueError('机构页面重定向异常')
            rows=public_records(key,content);counts=import_reports(pipeline,key,rows)
            all_states[key]={'status':'succeeded','last_attempt_at':now_iso(),'last_success_at':now_iso(),'message':f'已同步{len(rows)}条公开索引，不含研报全文','counts':counts}
        except (httpx.HTTPError,UnicodeError,ET.ParseError,ValueError) as exc:
            message=str(exc) if isinstance(exc,ValueError) else '官方公开入口暂不可达或返回异常，保留此前数据'
            all_states[key]={**all_states.get(key,{}),'status':'failed','last_attempt_at':now_iso(),'message':message}
            atomic_write_json(path,all_states);raise ValueError(message) from None
        atomic_write_json(path,all_states);return all_states[key]
