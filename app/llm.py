"""Durable local receipts, idempotency and request-count circuit breaker."""
import json
import threading
import httpx
from .storage import atomic_write_json, read_json
from .utils import now_iso, sha256_text, today_str


class LLMError(RuntimeError):
    pass


class ReceiptClient:
    def __init__(self, storage, settings, secret, transport=None):
        self.storage, self.settings, self.secret = storage, settings, secret
        self.transport = transport
        self.lock = threading.RLock()

    def receipts(self):
        return [read_json(p) for p in self.storage.path('jobs/model-receipts').glob('*.json')]

    def usage(self):
        attempts = [a for r in self.receipts() for a in r.get('attempts', []) if a['at'][:10] == today_str()]
        return {'requests': len(attempts), 'tokens': sum(a.get('total_tokens', 0) for a in attempts),
                'limit': self.settings().get('daily_request_limit', 400),
                'unknown': sum(a.get('status') in {'unknown','pending'} for a in attempts)}

    def call(self, system, body, purpose, max_tokens=3000):
        # Mac publisher and desktop analysis share the same quota and receipts.
        import fcntl
        lock_path=self.storage.path('jobs/model-api.lock')
        lock_path.parent.mkdir(parents=True,exist_ok=True)
        with lock_path.open('a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX)
            try:return self._call(system,body,purpose,max_tokens)
            finally:fcntl.flock(handle,fcntl.LOCK_UN)

    def _call(self, system, body, purpose, max_tokens=3000):
        model = self.settings()['model']
        identity = sha256_text(json.dumps([model, purpose, system, body, max_tokens], ensure_ascii=False))
        path = self.storage.path(f'jobs/model-receipts/{identity}.json')
        if max_tokens==6500 and purpose.startswith('finance-assessment-'):
            prior_id=sha256_text(json.dumps([model,purpose,system,body,4500],ensure_ascii=False))
            prior_path=self.storage.path(f'jobs/model-receipts/{prior_id}.json')
            prior=read_json(prior_path)
            if prior and prior.get('status')=='succeeded':
                if getattr(self,'document_ids',None):
                    references=sorted(set(prior.get('document_ids',[]))|set(self.document_ids))
                    if references!=prior.get('document_ids'):
                        prior['document_ids']=references
                        atomic_write_json(prior_path,prior)
                return prior['result']
        with self.lock:
            receipt = read_json(path) or {'id': identity, 'model': model, 'purpose': purpose, 'attempts': []}
            if getattr(self,'document_ids',None) and receipt.get('document_ids')!=self.document_ids:
                receipt['document_ids']=sorted(set(receipt.get('document_ids',[]))|set(self.document_ids))
                if path.exists():
                    atomic_write_json(path,receipt)
            if receipt.get('status') == 'succeeded':
                return receipt['result']
            if receipt.get('status') in {'pending', 'unknown'}:
                raise LLMError('上次模型请求结果未确认，已暂停重复调用；请在请求记录中核对并解除暂停')
            if self.usage()['requests'] >= self.settings().get('daily_request_limit', 400):
                raise LLMError('已达到今日模型请求上限；已完成结果会保留，明日或调整上限后可继续')
            key = self.secret()
            if not key:
                raise LLMError('请先设置 DeepSeek API Key')
            attempt = {'at': now_iso(), 'status': 'pending'}
            receipt['attempts'].append(attempt)
            receipt.update(status='pending', updated_at=now_iso())
            atomic_write_json(path, receipt)
            try:
                with httpx.Client(timeout=120, transport=self.transport) as client:
                    response = client.post('https://api.deepseek.com/chat/completions', headers={'Authorization':'Bearer '+key},
                        json={'model':model, 'messages':[{'role':'system','content':system},{'role':'user','content':body}],
                              'thinking':{'type':'disabled'},'response_format':{'type':'json_object'},'max_tokens':max_tokens})
                if response.status_code != 200:
                    attempt.update(status='failed', http_status=response.status_code)
                    receipt.update(status='failed')
                    raise LLMError(f'模型请求失败（HTTP {response.status_code}），可检查设置后重试')
                payload = response.json()
                usage = payload.get('usage') or {}
                attempt.update(total_tokens=int(usage.get('total_tokens') or 0))
                result = json.loads(payload['choices'][0]['message']['content'])
                if not isinstance(result, dict):
                    raise ValueError()
                attempt['status'] = 'succeeded'
                receipt.update(status='succeeded', result=result)
                return result
            except LLMError:
                raise
            except (ValueError, KeyError, IndexError, TypeError):
                attempt['status'] = 'invalid'
                receipt['status'] = 'failed'
                raise LLMError('模型返回的结构不完整，本次请求已记录，可重试') from None
            except Exception:
                attempt['status'] = 'unknown'
                receipt['status'] = 'unknown'
                raise LLMError('网络中断，模型请求结果未确认，已记录并暂停重复请求') from None
            finally:
                receipt['updated_at'] = now_iso()
                atomic_write_json(path, receipt)

    def invalidate(self, system, body, purpose, max_tokens=3000):
        capacities=[max_tokens]
        if max_tokens==6500 and purpose.startswith('finance-assessment-'):
            capacities.append(4500)
        with self.lock:
            for capacity in capacities:
                identity=sha256_text(json.dumps([self.settings()['model'],purpose,system,body,capacity],ensure_ascii=False))
                path=self.storage.path(f'jobs/model-receipts/{identity}.json')
                row=read_json(path)
                if row and row.get('status')=='succeeded':
                    row.update(status='failed',schema_error='结果未通过业务字段校验',updated_at=now_iso())
                    row.pop('result',None)
                    if row.get('attempts'):
                        row['attempts'][-1]['status']='invalid'
                    atomic_write_json(path,row)

    def release(self, identity):
        import re
        if not re.fullmatch(r'[a-f0-9]{64}', identity):
            raise LLMError('请求编号无效')
        with self.lock:
            path = self.storage.path(f'jobs/model-receipts/{identity}.json')
            row = read_json(path)
            if not row or row.get('status') not in {'unknown','pending'}:
                raise LLMError('该请求无需解除暂停')
            row.update(status='released', released_at=now_iso())
            atomic_write_json(path, row)
