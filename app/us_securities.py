"""Official Nasdaq Trader equity directory, local aliases and conservative US matching."""
import csv,io,re
import httpx
from .utils import now_iso
US_SOURCE='https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt'
# Aliases are enabled only while the official name still contains the expected issuer.
ALIASES={
 'NVDA':('nvidia',['英伟达','辉达','NVIDIA']), 'AAPL':('apple',['苹果','苹果公司','Apple']),
 'MSFT':('microsoft',['微软','Microsoft']), 'AMZN':('amazon',['亚马逊','Amazon']),
 'META':('meta',['Meta','脸书','Facebook']), 'TSLA':('tesla',['特斯拉','Tesla']),
 'AMD':('advanced micro devices',['AMD','超威半导体']), 'AVGO':('broadcom',['博通','Broadcom']),
 'INTC':('intel',['英特尔','Intel']), 'MU':('micron',['美光','Micron']),
 'TSM':('taiwan semiconductor',['台积电','台積電','TSMC']), 'ASML':('asml',['阿斯麦','ASML']),
 'GOOG':('alphabet',['谷歌','谷歌C','Google','Alphabet']), 'GOOGL':('alphabet',['谷歌','谷歌A','Google','Alphabet']),
 'ORCL':('oracle',['甲骨文','Oracle']), 'PLTR':('palantir',['帕兰提尔','Palantir']),
 'QCOM':('qualcomm',['高通','Qualcomm']), 'NFLX':('netflix',['奈飞','Netflix']),
 'CRM':('salesforce',['赛富时','Salesforce']), 'ADBE':('adobe',['奥多比','Adobe']),
 'DELL':('dell',['戴尔','Dell']), 'ANET':('arista',['Arista']), 'MRVL':('marvell',['迈威尔','Marvell']),
 'ARM':('arm',['安谋','Arm Holdings']), 'COIN':('coinbase',['Coinbase']),
 'APP':('applovin',['AppLovin']), 'SMCI':('super micro',['超微电脑','Supermicro']),
 'AMAT':('applied materials',['应用材料']), 'LRCX':('lam research',['泛林集团']),
 'KLAC':('kla',['科磊']), 'SNOW':('snowflake',['Snowflake']),
}

def issuer_name(name):
    return re.split(r'\s+-\s+|\s+(?:Class\s+[A-Z0-9-]+\s+|Common Stock|Ordinary Shares|American Depositary)',name,flags=re.I)[0].strip()

def parse(text):
    reader=csv.DictReader(io.StringIO(text),delimiter='|');required={'Symbol','Security Name','Listing Exchange','ETF','Test Issue'}
    if not required.issubset(reader.fieldnames or []):raise ValueError('美股目录格式变化')
    result=[]
    for r in reader:
        code=r.get('Symbol','');name=r.get('Security Name','')
        if r.get('Test Issue')!='N' or r.get('ETF')!='N' or r.get('Listing Exchange') not in {'Q','N','A','P','Z','V'}:continue
        if not re.fullmatch(r'[A-Z]{1,5}(?:[.][A-Z])?',code):continue
        if re.search(r'\bwarrants?\b|\bpreferred\b|\brights\b|\bunits\b|\bnotes\b|\bfund\b',name,re.I):continue
        if name:result.append({'code':code,'name':issuer_name(name),'english_name':name})
    if not result:raise ValueError('美股普通股目录为空')
    return result

def fetch():
    try:
        r=httpx.get(US_SOURCE,timeout=45,follow_redirects=True);r.raise_for_status();rows=parse(r.text)
        if len(rows)<1000:raise ValueError('美股目录数量异常，保留原库')
        return rows
    except httpx.HTTPError:raise ValueError('美股官方目录暂不可达，保留原库') from None

def ingest(catalog,rows):
    from .securities import normalized
    valid={}
    for row in rows:
        if not re.fullmatch(r'[A-Z]{1,5}(?:[.][A-Z])?',row.get('code','')) or not row.get('name'):raise ValueError('无效美股代码')
        if row['code'] in valid and valid[row['code']]['name']!=row['name']:raise ValueError('美股代码冲突')
        valid[row['code']]=row
    if not valid:raise ValueError('美股目录为空')
    stamp=now_iso()
    with catalog.connect() as c:
        old=c.execute("SELECT count(*) FROM securities WHERE exchange='us' AND in_directory=1").fetchone()[0]
        if old and len(valid)<old*.8:raise ValueError('美股目录数量异常下降，保留原库')
        # Rebuild US aliases to avoid attaching a recycled ticker to its former issuer.
        c.execute("DELETE FROM security_names WHERE security_id IN (SELECT security_id FROM securities WHERE exchange='us')")
        c.execute("UPDATE securities SET in_directory=0 WHERE exchange='us'")
        for code,row in valid.items():
            key='us'+code;english=row.get('english_name',row['name']);name=row['name']
            c.execute('''INSERT INTO securities VALUES(?,?,?,?,?,?,?,?,1) ON CONFLICT(security_id) DO UPDATE SET name=excluded.name,pinyin=excluded.pinyin,source=excluded.source,fetched_at=excluded.fetched_at,in_directory=1''',(key,code,'us',name,english,'',US_SOURCE,stamp))
            aliases={name,english,code+'.US'}
            if len(code)>=3 and code not in {'APP','ARM','CEO','API','GDP','USA','ALL','NOW','NET','DOC','FOR','OUT'}:aliases.add(code)
            # Deterministic corporate suffix normalization, never fuzzy substring matching.
            short=re.sub(r'[, ]+(?:incorporated|inc[.]?|corporation|corp[.]?|limited|ltd[.]?|plc)[, .]*$','',name,flags=re.I)
            if len(short)>=3:aliases.add(short)
            expected,common=ALIASES.get(code,('',[]))
            if expected and expected in english.casefold():aliases.update(common)
            for alias in aliases:c.execute('INSERT INTO security_names VALUES(?,?,?,?,?)',(key,alias,normalized(alias),stamp,stamp))
        c.execute('INSERT INTO security_syncs(updated_at,count,source) VALUES(?,?,?)',(stamp,len(valid),US_SOURCE))
    return catalog.stats()

def matches(catalog,names):
    from .securities import normalized
    grouped={}
    with catalog.connect() as c:
        for r in c.execute("SELECT s.*,n.normalized FROM securities s JOIN security_names n USING(security_id) WHERE s.exchange='us' AND s.in_directory=1"):
            grouped.setdefault(r['normalized'],{})[r['security_id']]=dict(r)
    result={}
    for name in names:
        rows=list(grouped.get(normalized(name),{}).values())
        if rows and len({normalized(r['name']) for r in rows})==1:result[name]=rows
    return result


def main():
    import argparse
    from pathlib import Path
    from .config import load_config
    from .storage import Storage
    from .securities import Securities
    parser=argparse.ArgumentParser(description='Refresh the official US equity directory without model calls')
    parser.add_argument('--file',type=Path,help='Previously downloaded official Nasdaq Trader nasdaqtraded.txt')
    args=parser.parse_args();rows=parse(args.file.read_text()) if args.file else fetch()
    stats=ingest(Securities(Storage(load_config().data_dir)),rows)
    print({'us_count':stats['us_count'],'model_requests':0})

if __name__=='__main__':main()
