"""Small read-only MCP 2025-11-25 JSON transport backed by publication views."""
import json

TOOLS = [
    {'name':'search_research','description':'全文检索本机财经资料，返回标题、摘要、原文链接与检索片段。','inputSchema':{'type':'object','properties':{'query':{'type':'string','maxLength':200}},'required':['query'],'additionalProperties':False}},
    {'name':'list_stocks','description':'查找公司及稳定 stock_id，供获取个股调研时间线使用。','inputSchema':{'type':'object','properties':{'query':{'type':'string','maxLength':100}},'additionalProperties':False}},
    {'name':'stock_timeline','description':'按发布日期获取个股调研、预测、数据差异和原文证据。','inputSchema':{'type':'object','properties':{'stock_id':{'type':'string'},'order':{'type':'string','enum':['asc','desc']}},'required':['stock_id'],'additionalProperties':False}},
    {'name':'research_briefing','description':'获取日报、周报或月报，保留每条资料的来源。','inputSchema':{'type':'object','properties':{'date':{'type':'string','description':'YYYY-MM-DD'},'period':{'type':'string','enum':['day','week','month']}},'additionalProperties':False}},
    {'name':'research_events','description':'获取事件与近48小时已知独立信源的热度，不是投资评分。','inputSchema':{'type':'object','properties':{},'additionalProperties':False}},
]
for tool in TOOLS:
    tool['annotations']={'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True,'openWorldHint':False}


def call_tool(publication, name, args, window):
    schema=next((t['inputSchema'] for t in TOOLS if t['name']==name),None)
    if schema is None or not isinstance(args,dict) or set(args)-set(schema['properties']) or any(k not in args for k in schema.get('required',[])):
        raise ValueError('工具名或参数无效')
    if any(not isinstance(v,str) or len(v)>200 for v in args.values()):
        raise ValueError('参数必须为长度不超过200的字符串')
    if name=='search_research':
        return {'documents':publication.search(args['query'])}
    if name=='list_stocks':
        q=args.get('query','').casefold()
        return {'stocks':[{k:v for k,v in s.items() if k!='document_ids'} for s in publication.stocks() if not q or q in (s['name']+' '+s['code']).casefold()][:50]}
    if name=='stock_timeline':
        order=args.get('order','desc')
        if order not in {'asc','desc'}:
            raise ValueError('排序无效')
        value=publication.stock_timeline(args['stock_id'],order)
        if not value:
            raise ValueError('个股不存在，先调用 list_stocks 获取 stock_id')
        value['entries']=value['entries'][:30]
        return value
    if name=='research_briefing':
        start,end=window(args.get('date',''),args.get('period','day'))
        return publication.digest(start,end)
    if name=='research_events':
        return {'events':publication.events()[:30]}
    raise ValueError('工具不存在')
