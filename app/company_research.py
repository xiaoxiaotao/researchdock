"""Human company identity links and personal research journals, separate from source evidence."""
import re
from .storage import read_json,atomic_write_json
from .utils import now_iso,ulid

KEY=re.compile(r'[A-Za-z0-9_.-]{1,100}')

def identities(storage):
    return read_json(storage.path('catalog/company-identities.json')) or {}

def resolve(key,links):
    seen=set()
    while key in links and key not in seen:
        seen.add(key);key=links[key]['target']
    return key

def merge(storage,source,target,known):
    if source==target or source not in known or target not in known:raise ValueError('请选择两个不同且存在的公司条目')
    links=identities(storage)
    if resolve(target,links)==source:raise ValueError('归并会形成循环，请先撤销已有归并')
    links[source]={'target':target,'updated_at':now_iso()}
    atomic_write_json(storage.path('catalog/company-identities.json'),links)

def journal(storage):
    return read_json(storage.path('catalog/company-journal.json')) or {}

def save_note(storage,company,data,known,documents,known_versions=None):
    if company not in known:raise ValueError('公司不存在')
    if not isinstance(data,dict):raise ValueError('笔记参数无效')
    text=data.get('text','')
    topic=data.get('topic','研究逻辑')
    document=data.get('document_id','')
    if not isinstance(text,str) or not text.strip() or len(text)>10000:raise ValueError('笔记需为1至10000字')
    if topic not in ('研究逻辑','订单','产能','价格','盈利预测','风险','待验证'):raise ValueError('研究主题无效')
    if document and document not in documents:raise ValueError('关联资料不属于该公司')
    data_all=journal(storage)
    note={'id':'note_'+ulid(),'company_id':company,'topic':topic,'text':text.strip(),'document_id':document,'created_at':now_iso(),'deleted':False}
    if document and known_versions is not None:note['document_revision']=known_versions.get(document)
    if topic=='待验证':
        note['question_state']='open'
        if known_versions is not None:note['known_document_versions']=known_versions
    data_all[note['id']]=note
    atomic_write_json(storage.path('catalog/company-journal.json'),data_all)
    return note

QUESTION_STATES={'open':'待验证','supported':'个人判断：证据支持','refuted':'个人判断：证据反驳','inconclusive':'暂无法判断'}

def update_question(storage,note_id,data,documents):
    notes=journal(storage)
    note=notes.get(note_id)
    if not note or note.get('topic')!='待验证':raise ValueError('待验证记录不存在')
    if not isinstance(data,dict) or not isinstance(data.get('state'),str) or data.get('state') not in QUESTION_STATES:raise ValueError('问题状态无效')
    state=data['state'];reason=data.get('conclusion','');refs=data.get('document_ids',[])
    if not isinstance(reason,str) or len(reason)>3000 or (state!='open' and not reason.strip()):raise ValueError('请填写1至3000字的判断依据')
    if not isinstance(refs,list) or len(refs)>20 or any(not isinstance(ref,str) or ref not in documents for ref in refs):raise ValueError('证据资料不属于当前公司')
    if state in ('supported','refuted') and not refs:raise ValueError('支持或反驳的个人判断需至少关联一份原文证据')
    event={'from_state':note.get('question_state','open'),'state':state,'conclusion':reason.strip(),'document_ids':sorted(set(refs)),'document_revisions':{doc:documents[doc] for doc in refs} if isinstance(documents,dict) else {},'updated_at':now_iso()}
    if note.get('question_state','open')==state and note.get('question_conclusion','')==event['conclusion'] and note.get('question_evidence',[])==event['document_ids'] and note.get('question_evidence_revisions',{})==event['document_revisions']:return note
    note.setdefault('question_history',[]).append(event)
    note.update(question_state=state,question_conclusion=event['conclusion'],question_evidence=event['document_ids'],question_evidence_revisions=event['document_revisions'],question_updated_at=event['updated_at'])
    atomic_write_json(storage.path('catalog/company-journal.json'),notes)
    return note
