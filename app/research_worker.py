"""Mac-initiated execution, one bounded task at a time; publication stays non-blocking."""
from concurrent.futures import ThreadPoolExecutor
import httpx
from .storage import read_json
from .llm import ReceiptClient
from .research import Secrets
from .research_assistant import generate

def disable_research(url,token,transport=None):
    with httpx.Client(timeout=15,follow_redirects=False,transport=transport,headers={'Authorization':'Bearer '+token}) as client:
        response=client.post(url.rstrip('/')+'/v1/research/config',json={'enabled':False,'daily_limit':10})
        if response.status_code!=404:response.raise_for_status()

class BackgroundResearch:
    def __init__(self,cfg,storage,url,token,daily_limit=10,transport=None):
        self.cfg,self.storage,self.url,self.token=cfg,storage,url.rstrip('/'),token
        self.daily_limit=max(1,min(30,int(daily_limit)));self.transport=transport
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='mobile-research');self.current=None
        def settings():return {'model':'deepseek-flash','daily_request_limit':400,**(read_json(storage.path('catalog/research-settings.json')) or {})}
        self.provider=ReceiptClient(storage,settings,Secrets(storage).get)
    def tick(self):
        with httpx.Client(timeout=20,follow_redirects=False,transport=self.transport,headers={'Authorization':'Bearer '+self.token}) as client:
            r=client.post(self.url+'/v1/research/config',json={'enabled':True,'daily_limit':self.daily_limit})
            if r.status_code==404:return
            r.raise_for_status()
            if self.current:
                task,future=self.current
                if not future.done():return
                result=future.result()
                response=client.post(self.url+'/v1/research/tasks/'+task['id']+'/complete',json=dict(result,lease=task['lease']))
                if response.status_code not in (200,409):response.raise_for_status()
                self.current=None
            task=client.post(self.url+'/v1/research/claim');task.raise_for_status();task=task.json().get('task')
            if task:self.current=(task,self.pool.submit(generate,self.cfg,self.storage,task,self.provider))
    def close(self):self.pool.shutdown(wait=True)
