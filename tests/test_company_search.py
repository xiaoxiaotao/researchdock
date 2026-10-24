import unittest
from app.company_search import filter_entries

class CompanySearchTests(unittest.TestCase):
    def test_literal_context_and_date_order(self):
        rows=[{'document_id':'a','revision':2,'published_at':'2026-10-21T20:00:00+08:00'}, {'document_id':'b','revision':1,'published_at':None}]
        bodies={'a':'订单 <script>x</script> 改善。订单回款。','b':'订单增长'}
        found=filter_entries(rows,bodies,'订单','2026-10-20','2026-10-22')
        self.assertEqual(len(found),1);self.assertEqual(found[0]['source_match_count'],2)
        self.assertEqual(found[0]['revision'],2);self.assertIn('<script>',found[0]['source_matches'][0]['after'])
        self.assertEqual(filter_entries(rows,bodies,'利润'),[])
        self.assertEqual(len(filter_entries(rows,bodies)),2)
        self.assertNotIn('source_matches',rows[0])
    def test_cap_unicode_offsets_and_literal_metacharacters(self):
        row={'document_id':'a','published_at':'2026-10-21'}
        found=filter_entries([row],{'a':'İ订单 [现金流] '+'订单 '*5},'订单')[0]
        self.assertEqual(len(found['source_matches']),3);self.assertEqual(found['source_match_count'],6)
        self.assertEqual(found['source_matches'][0]['text'],'订单')
        self.assertEqual(len(filter_entries([row],{'a':'[现金流]'},'[现金流]')),1)
    def test_invalid_ranges(self):
        for start,end in [('wrong',''),('2026-10-22','2026-10-21')]:
            with self.assertRaises(ValueError):filter_entries([],{},start=start,end=end)
        with self.assertRaises(ValueError):filter_entries([],{},'x'*201)
    def test_source_focus_keeps_revision_body_and_handles_missing_or_overflow(self):
        from app.company_search import source_focus
        result=source_focus('订单第一处。İ订单第二处。订单第三处。','订单',2)
        self.assertEqual(result['hit'],2);self.assertEqual(result['total'],3)
        self.assertIn('第二处',result['match']['after'])
        self.assertEqual(source_focus('订单','订单',100)['hit'],1)
        self.assertEqual(source_focus('旧版没有该词','新订单')['total'],0)
        self.assertIsNone(source_focus('abc','')['match'])
        for value in (0,-1,True):
            with self.assertRaises(ValueError):source_focus('订单','订单',value)
    def test_focus_template_escapes_source_and_encodes_navigation(self):
        from app.company_search import source_focus
        from app.web.app import templates
        template=templates.env.get_template('document_detail.html')
        # Exercise the actual source-focus block without unrelated document fixtures.
        source=templates.env.loader.get_source(templates.env,'document_detail.html')[0]
        block=source[source.index('{% if search_focus and'):source.index('{% if evidence_focus %}')]
        html=templates.env.from_string(block).render(search_focus=source_focus('订单 <script>bad</script> 订单','订单'),revision_row={'revision':2})
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html)
        self.assertIn('revision=2',html);self.assertIn('hit=2#search-match',html)
