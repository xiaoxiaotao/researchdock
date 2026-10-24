"""One read-only publication layer for pages, stock timelines, briefs and exports."""
import json
import math
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from urllib.parse import quote

from . import index
from .storage import read_json
from .measurements import comparison_key, different_value
from .utils import TZ, parse_iso, sha256_text, now_iso


def moment(value):
    stamp = parse_iso(value)
    return stamp.astimezone(TZ) if stamp else None


def plain_title(value):
    return re.sub(r'\s+', '', re.sub(r'[^\w\u4e00-\u9fff]', '', value)).casefold()


class Publications:
    def __init__(self, research):
        self.research, self.storage = research, research.storage
        self.notes = research.notes()
        with index.connect(research.pipeline.cfg.db_path) as conn:
            self.docs = {r['document_id']:dict(r) for r in conn.execute('SELECT * FROM documents WHERE deleted_at IS NULL')}
            self.bodies = {r['document_id']:r['body'] for r in conn.execute('SELECT document_id,body FROM document_search')}
            self.known = [dict(r) for r in index.list_stocks(conn)]
            self.relations = [dict(r) for r in conn.execute('SELECT * FROM document_stocks')]
        self.by_doc = {n['document_id']:n for n in self.notes}
        self._stocks = None
        self._events = None

    def reading_groups(self, notes):
        """One representative per existing event, after caller filters are applied."""
        event_ids={n['document_id']:event['event_id'] for event in self.events() for n in event['reports']}
        groups={}
        for note in notes:
            key=event_ids.get(note['document_id'],note['document_id'])
            groups.setdefault(key,[]).append(note)
        def rank(note):
            score=note.get('intelligence',{}).get('score')
            return (note.get('editorial',{}).get('selected') is True,score if type(score) is int else -1,note.get('published_at') or '',note['document_id'])
        result=[]
        for reports in groups.values():
            representative=max(reports,key=rank)
            result.append({**representative,'reading_group_reports':[{'document_id':n['document_id'],'title':n['title'],'published_at':n.get('published_at'),'source_name':n.get('source_name','来源未知')} for n in sorted(reports,key=lambda n:n.get('published_at') or '',reverse=True)],'reading_group_count':len(reports)})
        return sorted(result,key=lambda n:n.get('published_at') or '',reverse=True)

    def selected_reports(self, notes=None):
        events={n['document_id']:e['event_id'] for e in self.events() for n in e['reports']}
        seats={}
        for note in self.notes if notes is None else notes:
            if not note.get('is_selected'):
                continue
            key=events.get(note['document_id'],note['document_id'])
            def rank(value):
                score=value.get('intelligence',{}).get('score')
                return (value.get('editorial',{}).get('selected') is True, score if type(score) is int else -1, value.get('published_at') or '')
            if key not in seats or rank(note)>rank(seats[key]):
                seats[key]=note
        return sorted(seats.values(),key=lambda n:n.get('published_at') or '',reverse=True)

    def stocks(self):
        if self._stocks is not None:
            return self._stocks
        stocks = {}
        for row in self.known:
            stocks[row['stock_id']] = {**row, 'document_ids':set(), 'association':'导入资料关联', 'industries':set()}
        from .securities import Securities
        from .company_research import journal
        master=Securities(self.storage)
        saved={p.stem for p in self.storage.path('derived/financials').glob('security-*.json')}
        saved.update(n['company_id'] for n in journal(self.storage).values() if n.get('company_id','').startswith('security-'))
        for key in saved:
            security=master.get(key.removeprefix('security-'))
            if security:
                stocks[key]={'stock_id':key,'name':security['name'],'code':security['code'],'market':'港股' if security['exchange']=='hk' else 'A股','exchange':security['exchange'],'document_ids':set(),'industries':set(),'association':'证券目录公司，已保存财务或个人笔记'}
        for relation in self.relations:
            if relation['stock_id'] in stocks and relation['document_id'] in self.docs:
                stocks[relation['stock_id']]['document_ids'].add(relation['document_id'])
        for note in self.notes:
            body = self.bodies.get(note['document_id'], '')
            refs = list(note.get('stocks', []))
            for item in note.get('intelligence', {}).get('observations', []):
                refs.append({'name':item['company'], 'code':'', 'evidence':item['evidence']})
            for ref in refs:
                name, code, evidence = ref.get('name','').strip(), ref.get('code','').strip(), ref.get('evidence','')
                if not name or not evidence or evidence not in body or name not in body:
                    continue
                if code and (code not in body or not re.fullmatch(r'[A-Za-z0-9.\-]{1,16}', code)):
                    code = ''
                matched = [s for s in stocks.values() if code and s.get('code') == code]
                if len(matched) != 1:
                    matched = [s for s in stocks.values() if s.get('name') == name and (not code or not s.get('code') or s['code']==code)]
                key = matched[0]['stock_id'] if len(matched)==1 else ('code-'+sha256_text(code)[:16] if code else 'name-'+sha256_text(name)[:16])
                if key not in stocks:
                    stocks[key] = {'stock_id':key,'name':name,'code':code,'market':'待核实','exchange':'',
                                   'association':'AI 提及，待核实','document_ids':set(),'industries':set()}
                stocks[key]['document_ids'].add(note['document_id'])
                stocks[key]['industries'].update(note.get('industries', []))
        from .company_research import identities,resolve
        links=identities(self.storage)
        for key in list(stocks):
            target=resolve(key,links)
            if target!=key and target in stocks:
                source=stocks[key]
                primary=stocks[target]
                primary['document_ids'].update(source['document_ids'])
                primary['industries'].update(source['industries'])
                primary.setdefault('aliases',[]).extend([source.get('name',''),*source.get('aliases',[])])
                primary.setdefault('member_ids',[]).append(key)
                primary['association']='人工确认归并；保留原文证据'
                del stocks[key]
        for stock in stocks.values():
            rows = [self.docs[i] for i in stock['document_ids']]
            dates = [r['published_at'] for r in rows if r.get('published_at')]
            stock.update(doc_count=len(rows), first_at=min(dates,key=moment,default=None), last_at=max(dates,key=moment,default=None),
                         industries=sorted(stock['industries']))
        from .securities import Securities
        references=Securities(self.storage).matches(list(stocks.values()))
        for key,stock in stocks.items():
            stock['security']=references.get(key)
            if stock['security']:
                stock['catalog_code']=stock['security']['code']
                stock['catalog_exchange']=stock['security']['exchange']
        self._stocks = sorted(stocks.values(),key=lambda s:(-s['doc_count'],s['name'] or s['code']))
        return self._stocks

    def stock_timeline(self, key, order='desc'):
        stock = next((s for s in self.stocks() if s['stock_id']==key or key in s.get('member_ids',[])), None)
        if not stock and key.startswith('security-'):
            from .securities import Securities
            security=Securities(self.storage).get(key.removeprefix('security-'))
            if security:
                matches=[s for s in self.stocks() if (s.get('security') or {}).get('security_id')==security['security_id']]
                stock=matches[0] if len(matches)==1 else {'stock_id':key,'name':security['name'],'code':security['code'],'market':'港股' if security['exchange']=='hk' else 'A股','exchange':security['exchange'],'document_ids':set(),'industries':[],'association':'本地证券目录；暂无关联研究','security':security if security['in_directory'] else None,'catalog_code':security['code'],'catalog_exchange':security['exchange']}
                if security['exchange']=='hk' and len(matches)>1:
                    stock={**stock,'document_ids':set().union(*(s['document_ids'] for s in matches)),
                        'aliases':list(dict.fromkeys(n for s in matches for n in [s.get('name',''),*s.get('aliases',[])] if n)),
                        'member_ids':list(dict.fromkeys(n for s in matches for n in [s['stock_id'],*s.get('member_ids',[])])),
                        'industries':sorted(set().union(*(set(s.get('industries',[])) for s in matches))),
                        'association':'同一港股证券的已匹配名称汇总；原始公司记录保留'}

        if not stock:
            return None
        entries = []
        for docid in stock['document_ids']:
            doc = self.docs[docid]
            note = self.by_doc.get(docid, {})
            ai = note.get('intelligence', {})
            observations = [o for o in ai.get('observations', []) if o['company'] in [stock.get('name'),*stock.get('aliases',[])]]
            evidence = [r['evidence'] for r in note.get('stocks', []) if r.get('name') in [stock.get('name'),*stock.get('aliases',[])] and r.get('evidence')]
            if not observations:
                observations = [{'company':stock['name'], 'topic':'原文提及', 'metric':'','period':'','value':'','unit':'',
                                 'kind':'opinion','statement':e,'evidence':e} for e in dict.fromkeys(evidence)]
            year=moment(doc.get('published_at')).year if moment(doc.get('published_at')) else None
            observations=[{**o,'comparison_key':comparison_key(o,year)} for o in observations]
            entries.append({'document_id':docid,'revision':doc['current_revision'],'title':doc['title'],
                            'published_at':doc.get('published_at'), 'source_name':doc.get('institution') or doc.get('source_space_name') or doc.get('source_platform') or '来源未知',
                            'summary':note.get('summary','尚未生成 AI 摘要，可阅读归档原文'), 'source_url':doc.get('source_url'),
                            'observations':observations,'changes':[], 'new_statements':[], 'intelligence_ready':bool(ai)})
        # Unknown publication dates never get substituted with the import time.
        entries.sort(key=lambda e:(moment(e['published_at']) or datetime.min.replace(tzinfo=TZ),e['document_id']))
        previous = None
        metrics = {}
        for entry in entries:
            if not entry['published_at']:
                continue
            if previous:
                old_items = previous['observations']
                for current in entry['observations']:
                    if current.get('comparison_key'):
                        comparable = metrics.get(tuple(current['comparison_key']))
                        old, previous_metric = comparable if comparable else (None,None)
                        if old and different_value(old['value'],current['value']):
                            entry['changes'].append({'metric':current['metric'],'period':current['period'],'unit':current['unit'],
                                'before':old['value'],'after':current['value'],'kind':current['kind'],
                                'previous_id':previous_metric['document_id'],'previous_date':previous_metric['published_at'],
                                'previous_source':previous_metric['source_name'],'source':entry['source_name'],
                                'before_evidence':old['evidence'],'after_evidence':current['evidence'],
                                'label':'预测值表述差异' if current['kind']=='forecast' else '同口径数据表述差异'})
                    if not any(SequenceMatcher(None,current['statement'],o['statement']).ratio()>=.84 for o in old_items):
                        entry['new_statements'].append(current['statement'])
                entry['previous_id'] = previous['document_id']
            for observation in entry['observations']:
                if observation.get('comparison_key'):
                    metrics[tuple(observation['comparison_key'])] = (observation,entry)
            previous = entry
        if order=='desc':
            entries.reverse()
        known_dates = [e['published_at'] for e in entries if e['published_at']]
        return {'stock':{k:v for k,v in stock.items() if k!='document_ids'},'entries':entries,'total':len(entries),
                'first_at':min(known_dates,key=moment,default=None),'last_at':max(known_dates,key=moment,default=None),'order':order}

    def events(self, now=None):
        if self._events is not None and now is None:
            return self._events
        now = now or datetime.now(TZ)
        grouped = {}
        parent={n['document_id']:n['document_id'] for n in self.notes}
        separated={key for key,value in self.research.event_overrides().items() if value.get('separate')}
        def root(key):
            while parent[key]!=key:
                parent[key]=parent[parent[key]]
                key=parent[key]
            return key
        def union(a,b):
            if a in separated or b in separated:
                return
            a,b=root(a),root(b)
            parent[max(a,b)]=min(a,b)
        semantic=set()
        followups=[]
        for path in self.storage.path('derived/relations').glob('*.json'):
            relation=read_json(path)
            a,b=relation.get('a'),relation.get('b')
            if a not in self.by_doc or b not in self.by_doc or relation.get('model')!=self.research.settings()['model']:
                continue
            if self.by_doc[a]['revision']!=relation.get('a_revision') or self.by_doc[b]['revision']!=relation.get('b_revision'):
                continue
            if relation.get('relation')=='SAME_OCCURRENCE':
                union(a,b)
                semantic.update([a,b])
            elif relation.get('relation')=='SAME_STORY':
                followups.append(relation)
        seeds={}
        identities={}
        methods={}
        for note in self.notes:
            ai = note.get('intelligence', {})
            frame = ai.get('event') or {}
            date = moment(note.get('published_at'))
            # Two independent readings must agree. Earnings share an occurrence only for an explicit period.
            if frame and ai.get('independent_agreement') and frame.get('type')=='earnings' and re.fullmatch(r'20\d{2}(?:Q[1-4]|H[12]|FY)',frame.get('period','')):
                identity = f"earnings|{frame['subject']}|{frame['period']}"
                mode = '双次独立识别一致：同公司、同报告期业绩'
            else:
                normalized_title = plain_title(note['title'])
                identity = ('title|'+normalized_title) if len(normalized_title)>=18 else 'body|'+(note.get('input_hash') or note['document_id'])
                mode = '相同标题归组，待核实事件关系'
                # Identical titles from different months can be different reports.
                identity += '|'+(date.strftime('%Y-%m') if date else note['document_id'])
            if note['document_id'] in separated:
                identity='manual-separate|'+note['document_id']
                mode='人工确认：单独成事件，自动整理会保留'
            identities[note['document_id']]=identity
            methods[note['document_id']]=mode
            if identity in seeds:
                union(note['document_id'],seeds[identity])
            else:
                seeds[identity]=note['document_id']
        for note in self.notes:
            key=sha256_text(root(note['document_id']))[:20]
            mode='独立事件判断与复核一致：同一次发生' if note['document_id'] in semantic else methods[note['document_id']]
            event = grouped.setdefault(key, {'event_id':key,'title':note['title'],'reports':[], 'industries':set(), 'grouping_method':mode})
            event['reports'].append(note)
            event['industries'].update(note.get('industries', []))
        result = []
        for event in grouped.values():
            reports = sorted(event['reports'], key=lambda n:n.get('published_at') or '', reverse=True)
            source_latest = {}
            for note in reports:
                doc = self.docs.get(note['document_id'], {})
                stamp = moment(note.get('published_at'))
                if not stamp or stamp>now or now-stamp>timedelta(hours=48):
                    continue
                # Multiple posts in one planet are one known source, unless an institution was explicitly archived.
                source = doc.get('institution') or f"{doc.get('source_platform')}|{doc.get('source_space_id') or doc.get('source_url')}"
                source_latest[source] = max(source_latest.get(source,stamp),stamp)
            heat = sum(100*math.pow(.5,(now-stamp).total_seconds()/86400) for stamp in source_latest.values())
            before = now-timedelta(hours=6)
            earlier_sources = {}
            for note in reports:
                stamp=moment(note.get('published_at'))
                if stamp and before-timedelta(hours=48)<=stamp<=before:
                    doc=self.docs.get(note['document_id'],{})
                    source=doc.get('institution') or f"{doc.get('source_platform')}|{doc.get('source_space_id') or doc.get('source_url')}"
                    earlier_sources[source]=max(earlier_sources.get(source,stamp),stamp)
            previous_heat=sum(100*math.pow(.5,(before-stamp).total_seconds()/86400) for stamp in earlier_sources.values())
            scores = [n.get('intelligence',{}).get('score') for n in reports if type(n.get('intelligence',{}).get('score')) is int]
            event.update(reports=reports,industries=sorted(event['industries']), report_count=len(reports),
                         source_count=len(source_latest), heat=round(heat,1), heat_6h_ago=round(previous_heat,1), heat_delta=round(heat-previous_heat,1), trend=('new' if heat and not previous_heat else 'up' if heat>previous_heat else 'down' if heat<previous_heat else 'flat'), latest_at=reports[0].get('published_at'),
                         summary=reports[0]['summary'], score=max(scores,default=None), followups=[])
            for relation in followups:
                ids={n['document_id'] for n in reports}
                other=relation['b'] if relation['a'] in ids else relation['a'] if relation['b'] in ids else None
                if other and root(other)!=root(reports[0]['document_id']):
                    event['followups'].append({'event_id':sha256_text(root(other))[:20], 'title':self.by_doc[other]['title'],'reason':relation['judgement']['reason']})
            result.append(event)
        result.sort(key=lambda e:(e['heat'],e['latest_at'] or ''),reverse=True)
        self._events = result
        return result

    def digest(self, start, end, industry=''):
        selected = []
        for event in self.events():
            reports = [n for n in event['reports'] if n.get('published_at') and start <= moment(n['published_at']).date().isoformat() <= end and (not industry or industry in n['industries'])]
            if reports:
                item = {**event,'reports':reports,'summary':reports[0]['summary'],'title':reports[0]['title'],
                        'industries':sorted({i for n in reports for i in n['industries']}),'latest_at':reports[0].get('published_at'),
                        'score':max((n.get('intelligence',{}).get('score') for n in reports if type(n.get('intelligence',{}).get('score')) is int),default=None)}
                selected.append(item)
        selected.sort(key=lambda e:(e['score'] if e['score'] is not None else -1,e['latest_at'] or ''),reverse=True)
        sectors = {}
        for event in selected:
            for sector in event['industries']:
                if not industry or sector==industry:
                    sectors.setdefault(sector,[]).append(event)
        return {'start':start,'end':end,'industry':industry,'event_count':len(selected),
                'report_count':len({n['document_id'] for e in selected for n in e['reports']}),
                'sections':[{'industry':k,'events':v} for k,v in sectors.items()],
                'scored_report_count':len({n['document_id'] for e in selected for n in e['reports'] if type(n.get('intelligence',{}).get('score')) is int}),
                'generated_at':now_iso()}

    def search(self, query, limit=30):
        with index.connect(self.research.pipeline.cfg.db_path) as conn:
            docs,_ = index.list_documents(conn, q=query, limit=limit)
        return [{**dict(d),'ai_summary':self.by_doc.get(d['document_id'],{}).get('summary','')} for d in docs]
