import unittest
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from app.industries import categories, group_notes

class IndustryTests(unittest.TestCase):
    def test_aliases_merge_and_deduplicate(self):
        self.assertEqual(categories(['芯片', '半导体', '集成电路']), ['半导体'])
        self.assertEqual(categories(['医药', '医药生物']), ['医药生物'])
        self.assertEqual(categories([]), ['待分类'])

    def test_multi_industry_count_and_filter(self):
        notes = [dict(title='芯片资料', industries=['芯片', '人工智能']), dict(title='药企资料', industries=['医药']), dict(title='未知', industries=[])]
        groups, total = group_notes(notes)
        self.assertEqual(total, 3)
        self.assertEqual({g['name']:g['count'] for g in groups}, {'半导体':1, '人工智能':1, '医药生物':1, '待分类':1})
        groups, total = group_notes(notes, industry='半导体')
        self.assertEqual(total, 1)
        self.assertEqual([g['name'] for g in groups], ['半导体'])
        self.assertEqual(group_notes(notes, q='药企')[1], 1)

    def test_template_groups_have_own_articles(self):
        from app.web.app import templates
        from starlette.requests import Request
        notes = [dict(reading_day='2026-10-21',reading_time='12:00',document_id='one',title='芯片资料',industries=['芯片'],published_at='',model='test',revision=1,summary='摘要',key_points=[],stocks=[],risks=[]), dict(reading_day='2026-10-21',reading_time='13:00',document_id='two',title='医药资料',industries=['医药'],published_at='',model='test',revision=1,summary='摘要',key_points=[],stocks=[],risks=[])]
        groups, total = group_notes(notes)
        html = templates.env.get_template('reading.html').render(request=Request({'type':'http','path':'/reading','headers':[]}), groups=groups,feed_notes=notes,category_counts=groups,total=total,q='',industry='',storage_ready=True)
        self.assertEqual(html.count('class="timeline-row '), 2)
        self.assertEqual(html.count('class="day-section"'), 1)
        self.assertIn('id="item-two"', html)
        self.assertIn('半导体', html)
        self.assertIn('/documents/one', html)
        self.assertIn('/documents/two', html)
