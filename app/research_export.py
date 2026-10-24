"""Deterministic Markdown dossiers with source citations; never call a model."""
import re
from urllib.parse import quote
from .utils import now_iso


def text(value):
    return re.sub(r'([\\`*_{}\[\]<>#!|])',r'\\\1',str(value or '')).replace('\r','')


def dossier(timeline, base, notes=None):
    stock=timeline['stock']
    rows=[f"# {text(stock.get('name') or stock.get('code'))} · 调研档案",'',f"导出时间：{now_iso()}",f"代码：{text(stock.get('code') or '未知')} · 身份：{text(stock.get('association'))}",f"资料数：{timeline['total']} · 原文日期：{text(timeline.get('first_at') or '未知')} — {text(timeline.get('last_at') or '未知')}",'', '数据来自已归档原文及既有 AI 整理，不在导出时重新分析。缺失字段保持未知；数值表述差异不代表实际经营变化。']
    if stock.get('aliases'):rows += ['', '人工归并别名：'+ '、'.join(text(x) for x in stock['aliases'])]
    for entry in timeline['entries']:
        rows += ['',f"## {text(entry.get('published_at') or '日期未知')} · {text(entry['title'])}",f"来源：{text(entry['source_name'])} · 归档版本：{entry['revision']}",f"[本机归档]({base}/documents/{quote(entry['document_id'],safe='')})"]
        source=entry.get('source_url') or ''
        if source.startswith(('https://','http://')):rows += [f"[原始来源]({source.replace('(', '%28').replace(')', '%29')})"]
        rows += ['',text(entry['summary'])]
        for change in entry.get('changes',[]):
            rows += ['',f"**{text(change['label'])}**：{text(change['metric'])} · {text(change['period'])} · {text(change['before'])} → {text(change['after'])} {text(change['unit'])}",f"[前次归档]({base}/documents/{quote(change['previous_id'],safe='')})",'> 前次：'+text(change['before_evidence']).replace('\n','\n> '),'> 本次：'+text(change['after_evidence']).replace('\n','\n> ')]
        for point in entry.get('observations',[]):
            kind={'fact':'实际数据','forecast':'预测','opinion':'观点'}.get(point.get('kind'),'未分类')
            rows += ['',f"### {kind} · {text(point.get('topic'))}",text(point.get('statement')),f"指标：{text(point.get('metric') or '未提供')} · 报告期：{text(point.get('period') or '未核实')} · 数值：{text(point.get('value') or '未核实')} · 单位：{text(point.get('unit') or '未核实')}",'> 原文证据：'+text(point.get('evidence')).replace('\n','\n> ')]
    if notes is not None:
        rows += ['', '# 个人调研笔记', '', '以下为用户个人记录，与来源原文及 AI 整理分开。按笔记记录时间排列。']
        for note in notes:
            rows += ['',f"## {text(note['created_at'])} · {text(note['topic'])}",text(note['text'])]
            if note.get('topic')=='待验证':
                from .company_research import QUESTION_STATES
                rows += ['', '个人判断状态：'+QUESTION_STATES.get(note.get('question_state','open'),'待验证'),text(note.get('question_conclusion',''))]
                for event in note.get('question_history',[]):
                    rows += ['',text(event['updated_at'])+' · '+QUESTION_STATES[event['state']],text(event['conclusion'])]
                    for doc in event.get('document_ids',[]):
                        revision=event.get('document_revisions',{}).get(doc)
                        rows += [f"[当时引用的证据]({base}/documents/{quote(doc,safe='')}"+(f'?revision={revision}' if revision else '')+')']
            if note.get('document_id'):rows += [f"[关联资料]({base}/documents/{quote(note['document_id'],safe='')})"]
    return '\n'.join(rows)+'\n'
