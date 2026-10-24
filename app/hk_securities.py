"""HKEX equity reference feed; XLSX read with the standard library."""
import io,re,zipfile
import xml.etree.ElementTree as ET
import httpx

HK_SOURCE='https://www.hkex.com.hk/chi/services/trading/securities/securitieslists/ListOfSecurities_c.xlsx'
EN_SOURCE='https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx'

def sheet(content):
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        strings=[''.join(n.itertext()) for n in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',ns)]
        rows=[]
        for row in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//m:row',ns):
            values={}
            for cell in row:
                col=re.match('[A-Z]+',cell.attrib['r']).group();v=cell.find('m:v',ns)
                values[col]=strings[int(v.text)] if v is not None and cell.attrib.get('t')=='s' else (v.text or '' if v is not None else '')
            rows.append(values)
        return rows

def parse(chinese,english):
    cn={r.get('A'):r.get('B') for r in sheet(chinese)};result=[]
    for row in sheet(english):
        code=row.get('A','')
        if not re.fullmatch(r'\d{5}',code) or row.get('C')!='Equity' or row.get('Q')!='HKD':continue
        name=cn.get(code)
        if not name:raise ValueError('港股中英文清单不一致，保留原库')
        result.append({'code':code,'name':name,'english_name':row.get('B','')})
    return result

def fetch():
    try:
        responses=[httpx.get(url,timeout=60,follow_redirects=True) for url in (HK_SOURCE,EN_SOURCE)]
        for r in responses:r.raise_for_status()
        rows=parse(*(r.content for r in responses))
        if len(rows)<1000:raise ValueError('港股清单数据不完整，保留原库')
        return rows
    except (httpx.HTTPError,zipfile.BadZipFile,KeyError,ET.ParseError):raise ValueError('港交所清单暂不可用或格式变化，保留原库') from None
