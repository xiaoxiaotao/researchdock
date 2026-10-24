"""Shared industry categories for model output and reading navigation."""
import json

CATEGORIES = ('半导体', '人工智能', '计算机与软件', '通信', '消费电子', '传媒', '新能源', '电力与公用事业', '汽车', '机械设备', '国防军工', '医药生物', '食品饮料', '农林牧渔', '家电', '商贸零售', '美容护理', '纺织服装', '轻工制造', '银行', '非银金融', '房地产', '建筑建材', '基础化工', '有色金属', '钢铁', '煤炭', '石油石化', '交通运输', '环保', '社会服务', '综合', '宏观与策略')
ALIASES = {'芯片': '半导体', '集成电路': '半导体', 'AI': '人工智能', 'AI产业': '人工智能', '计算机': '计算机与软件', '软件': '计算机与软件', '医药': '医药生物', '医疗': '医药生物', '医药行业': '医药生物', '光伏': '新能源', '风电': '新能源', '储能': '新能源', '锂电池': '新能源', '电力设备': '新能源', '电力': '电力与公用事业', '公用事业': '电力与公用事业', '证券': '非银金融', '保险': '非银金融', '建筑材料': '建筑建材', '建筑装饰': '建筑建材', '宏观': '宏观与策略', '策略': '宏观与策略', '化工': '基础化工'}


def categories(values):
    result = []
    for value in values or []:
        category = ALIASES.get(value.strip(), value.strip())
        if category in CATEGORIES and category not in result:
            result.append(category)
    return result or ['待分类']


def group_notes(notes, q='', industry=''):
    groups = {}
    count = 0
    for note in notes:
        if q and q.casefold() not in json.dumps({k: note.get(k) for k in ('title', 'summary', 'industries', 'stocks', 'key_points', 'risks')}, ensure_ascii=False).casefold():
            continue
        labels = categories(note.get('industries', []))
        if industry and industry not in labels:
            continue
        count += 1
        for label in labels:
            if not industry or industry == label:
                groups.setdefault(label, []).append(note)
    order = (*CATEGORIES, '待分类')
    return [{'name': name, 'notes': groups[name], 'count': len(groups[name])} for name in order if name in groups], count
