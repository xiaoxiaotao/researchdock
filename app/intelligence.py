"""Two independent financial editorial assessments; only evidenced facts survive."""
from pathlib import Path
import re
from .utils import now_iso, sha256_text
from .storage import atomic_write_json, read_json
from .llm import LLMError

PROMPT = Path(__file__).with_name('prompts').joinpath('finance-assessment.md').read_text()
PROMPT_VERSION = sha256_text(PROMPT)[:12]
AXES = {'significance': 3, 'novelty': 2, 'evidence': 2, 'relevance': 1, 'traceability': 2}
VALIDATION_VERSION = 4
EVENT_TYPES = {'earnings','orders','capacity','product','policy','financing','research','other'}


def validate(value, body):
    axes = value.get('axes', {})
    if not isinstance(axes,dict):
        raise LLMError('评分维度必须为对象')
    if any(type(axes.get(k)) is not int or not 0 <= axes[k] <= 10 for k in AXES):
        raise LLMError('评分结构无效，未发布精选结论')
    score = sum(axes[k] * w for k,w in AXES.items())
    event = value.get('event') or {}
    if not isinstance(event,dict):
        event={}
    fields = ('subject','type','period','object','evidence')
    if any(not isinstance(event.get(k), str) for k in fields):
        event = {}
    if event and (event['type'] not in EVENT_TYPES or not event['evidence'] or event['evidence'] not in body or
                  event['subject'] not in body or not event['subject']):
        event = {}
    if event and (not event['object'] or event['object'] not in body):
        event = {**event,'object':event['evidence'][:160]}
    observations = []
    raw_observations=value.get('observations') or []
    if not isinstance(raw_observations,list):
        raise LLMError('调研观察字段必须为列表')
    company_names = {o.get('company') for o in raw_observations if isinstance(o,dict) and isinstance(o.get('company'),str) and o.get('company')}
    for item in raw_observations[:15]:
        required = ('company','topic','metric','period','value','unit','kind','statement','evidence')
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) for k in required):
            continue
        if item['kind'] not in {'fact','forecast','opinion'} or not item['company'] or item['company'] not in body or not item['evidence'] or item['evidence'] not in body:
            continue
        item = dict(item)
        original_quote = item['evidence']
        # When a quotation omits the subject, retain the contiguous source context that supplies it.
        if item['company'] not in item['evidence']:
            start = body.find(item['evidence'])
            company_at = body.rfind(item['company'],0,start+1)
            others = [body.rfind(name,0,start+1) for name in company_names if name!=item['company']]
            if company_at<0 or start-company_at>2000 or any(position>company_at for position in others):
                continue
            item['evidence'] = body[company_at:start+len(item['evidence'])]
        # Preserve source-backed observations while excluding unverified numeric fields from comparison.
        for field in ('value','unit','period'):
            if item[field] and item[field] not in original_quote:
                item[field] = ''
        if not item['period']:
            periods = set(re.findall(r'(?<![0-9])(?:20[0-9]{2}|[0-9]{2})\s*(?:Q[1-4](?:\s*[-~～]\s*Q?[1-4])?|H[12]|年前三季度|年上半年|年前三季|年全年)', original_quote, re.I))
            if len(periods)==1:
                item['period']=periods.pop()
        if item['value'] and not item['unit']:
            unit = re.search(re.escape(item['value'])+r'\s*(亿元|万元|亿美元|万美元|亿港元|亿|万|元|%|％|GW|MW|GWh|MWh|吨|台|套)',original_quote,re.I)
            if unit:
                item['unit']=unit.group(1)
        observations.append({k: item[k][:3000] for k in required})
    reason = value.get('reason')
    if not isinstance(reason, str):
        raise LLMError('缺少评分理由')
    return {'axes': axes, 'score': score, 'reason': reason[:500], 'event':event, 'observations':observations}


def assessment_path(storage, note, model):
    key = sha256_text(f"{note['document_id']}|{note['revision']}|{model}|{PROMPT_VERSION}")
    return storage.path(f'derived/intelligence/{key}.json')


def assess(storage, provider, note, body, model):
    provider.document_ids=[note['document_id']]
    path = assessment_path(storage, note, model)
    previous = read_json(path)
    if previous and previous.get('validation_version')==VALIDATION_VERSION:
        return previous
    if len(body) > 120000:
        raise LLMError('正文超长，暂不评分')
    if len(body.strip()) < 12 or body.startswith('此主题仅含附件'):
        result = {'status':'insufficient', 'score':None, 'reason':'正文信息不足，保留原文，不进入自动精选', 'observations':[], 'event':{}}
    else:
        def get(purpose):
            result=provider.call(PROMPT,body,purpose,6500)
            try:
                return validate(result,body)
            except LLMError:
                if hasattr(provider,'invalidate'):
                    provider.invalidate(PROMPT,body,purpose,6500)
                raise
        a = get('finance-assessment-a:'+PROMPT_VERSION)
        b = get('finance-assessment-b:'+PROMPT_VERSION)
        frame={}
        if a['event'] and b['event'] and all(a['event'].get(k)==b['event'].get(k) for k in ('subject','type')):
            same_period=a['event']['period']==b['event']['period']
            if same_period and (a['event']['type']=='earnings' or a['event']['object']==b['event']['object']):
                frame=a['event']
        candidate=a['event'] or b['event']
        # Conservative selection: a high score from one run cannot override a weak second assessment.
        result = {'status':'assessed','score':min(a['score'],b['score']), 'scores':[a['score'],b['score']],
                  'reason':a['reason'], 'review_reason':b['reason'], 'axes':[a['axes'],b['axes']], 'event':frame,
                  'observations':a['observations'], 'event_candidate':candidate, 'independent_agreement':bool(frame)}
    result.update(document_id=note['document_id'], revision=note['revision'], model=model,
                  prompt_version=PROMPT_VERSION, validation_version=VALIDATION_VERSION, generated_at=now_iso())
    atomic_write_json(path, result)
    return result
