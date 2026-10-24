import io,zipfile,unittest
from app.hk_securities import parse

def workbook(rows):
    from xml.sax.saxutils import escape
    strings=[];xml=[]
    for i,row in enumerate(rows,1):
        cells=[]
        for col,value in row.items():
            strings.append(value);cells.append(f'<c r="{col}{i}" t="s"><v>{len(strings)-1}</v></c>')
        xml.append('<row>'+''.join(cells)+'</row>')
    namespace='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('xl/sharedStrings.xml',f'<sst xmlns="{namespace}">'+''.join('<si><t>'+escape(t)+'</t></si>' for t in strings)+'</sst>')
        z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="{namespace}"><sheetData>'+''.join(xml)+'</sheetData></worksheet>')
    return out.getvalue()

class HKFeedTests(unittest.TestCase):
    def test_equities_only_hkd_and_chinese_join(self):
        english=[{'A':'00700','B':'TENCENT','C':'Equity','Q':'HKD'},{'A':'80700','B':'TENCENT-R','C':'Equity','Q':'CNY'},{'A':'02800','B':'ETF','C':'Exchange Traded Products','Q':'HKD'}]
        chinese=[{'A':'00700','B':'騰訊控股'}]
        rows=parse(workbook(chinese),workbook(english))
        self.assertEqual(rows,[{'code':'00700','name':'騰訊控股','english_name':'TENCENT'}])
        with self.assertRaises(ValueError):parse(workbook([]),workbook(english))
