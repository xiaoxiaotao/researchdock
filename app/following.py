"""Local watch preferences and transparent industry subtopic rules; no model calls."""
from .industries import CATEGORIES
from .storage import read_json, atomic_write_json
from .utils import now_iso

SUBTOPICS = {
 '半导体': {'芯片设计':('芯片设计','IC设计','GPU','CPU'), '制造与封测':('晶圆','代工','封测','先进封装'), '设备与材料':('光刻','刻蚀','半导体设备','电子特气')},
 '人工智能': {'算力与服务器':('算力','服务器','GPU'), '模型与应用':('大模型','智能体','Agent','模型训练'), '机器人与具身智能':('机器人','具身智能')},
 '通信': {'光通信':('光模块','光通信','CPO','光纤'), '卫星通信':('卫星通信','低轨卫星')},
 '机械设备': {'液冷与温控':('液冷','温控','冷却'), '工程与能源装备':('工程机械','油服','燃机','燃气轮机')},
 '新能源': {'光伏':('光伏','硅料','硅片'), '风电':('风电','风机'), '电池与储能':('动力电池','固态电池','储能','锂电')},
 '医药生物': {'创新药':('创新药','临床','ADC'), '医疗器械':('医疗器械','体外诊断','IVD'), '医疗服务':('医院','医疗服务')},
}

def subtopics(note, body):
    labels=[]
    text=(note.get('title','')+' '+body).casefold()
    for parent in note.get('industries',[]):
        for name,terms in SUBTOPICS.get(parent,{}).items():
            if any(term.casefold() in text for term in terms): labels.append((parent,name))
    return labels


def preferences(storage):
    return {'stocks':[], 'industries':[], 'seen':[], **(read_json(storage.path('catalog/following.json')) or {})}


def save_preferences(storage, data, known):
    if not isinstance(data,dict): raise ValueError('参数必须是对象')
    for field,allowed in [('stocks',known),('industries',set(CATEGORIES))]:
        if not isinstance(data.get(field),list) or any(not isinstance(v,str) or v not in allowed for v in data[field]): raise ValueError('关注对象无效，请刷新页面后重试')
    result=preferences(storage)
    result.update(stocks=list(dict.fromkeys(data['stocks'])),industries=list(dict.fromkeys(data['industries'])),updated_at=now_iso())
    atomic_write_json(storage.path('catalog/following.json'),result)
    return result


def matched_notes(publication, prefs):
    ids=set()
    for company in publication.stocks():
        if set([company['stock_id'],*company.get('member_ids',[])]) & set(prefs['stocks']): ids.update(company['document_ids'])
    seen=set(prefs['seen'])
    result=[]
    for note in publication.notes:
        if note['document_id'] in ids or set(note.get('industries',[])) & set(prefs['industries']):
            result.append({**note,'is_new':f"{note['document_id']}:{note['revision']}" not in seen})
    return result
