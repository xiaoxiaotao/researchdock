"""Public A-share financial statements, cached separately from AI research."""
import re
import threading
from decimal import Decimal,InvalidOperation
from .storage import read_json,atomic_write_json
from .utils import now_iso
import httpx

LOCK=threading.RLock()
ENDPOINT='https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022'
FIELDS={
 'lrb':{'revenue':('营业收入','BIZINCO'),'net_profit':('净利润','NETPROFIT'),'parent_profit':('归母净利润','PARENETP')},
 'llb':{'operating_cash':('经营现金流净额','MANANETR'),'investing_cash':('投资现金流净额','INVNETCASHFLOW'),'financing_cash':('筹资现金流净额','FINNETCFLOW')},
 'fzb':{'assets':('总资产','TOTASSET'),'liabilities':('总负债','TOTLIAB')},
}
LABELS={key:label for fields in FIELDS.values() for key,(label,_) in fields.items()}

class FinancialError(ValueError):pass

def cache(storage,key):
    return read_json(storage.path(f'derived/financials/{key}.json')) or {}

def numeric(value):
    if value is None or value in ('','--','-'):return None
    try:
        number=Decimal(str(value).replace(',',''))
        return str(number) if number.is_finite() else None
    except (InvalidOperation,ValueError):return None

def display(value):
    if value is None:return '—'
    return f'{Decimal(value)/Decimal(100000000):,.2f}'

def parse_statements(raw):
    periods={}
    for statement,fields in FIELDS.items():
        payload=raw.get(statement,{})
        result=payload.get('result') or {}
        if (result.get('status') or {}).get('code')!=0:raise FinancialError('数据源返回错误，保留上次成功数据')
        data=result.get('data') or {}
        reports=data.get('report_list')
        if not isinstance(reports,dict) or not reports:raise FinancialError('财报数据缺失或格式变化，保留上次成功数据')
        for period,report in reports.items():
            if not isinstance(report,dict):raise FinancialError('财报格式变化，保留上次成功数据')
            if not re.fullmatch(r'\d{8}',period) or period[4:] not in ('0331','0630','0930','1231'):continue
            if report.get('rCurrency')!='CNY' or '合并' not in report.get('rType',''):continue
            row=periods.setdefault(period,{'period':f'{period[:4]}-{period[4:6]}-{period[6:]}','period_label':period[:4]+{'0331':'年一季度','0630':'年上半年','0930':'年前三季度','1231':'年全年'}[period[4:]],'currency':'CNY','values':{},'statements':{}})
            items={item.get('item_field'):item for item in report.get('data',[]) if isinstance(item,dict)}
            for key,(_,field) in fields.items():row['values'][key]=numeric((items.get(field) or {}).get('item_value'))
            row['statements'][statement]={'publish_date':report.get('publish_date'),'report_type':report.get('rType'),'source':report.get('data_source'),'audit':report.get('is_audit'),'provider_updated_at':report.get('update_time')}
    if not periods or not any(any(v is not None for v in r['values'].values()) for r in periods.values()):raise FinancialError('未取得人民币合并财报，暂不展示该口径')
    for key,row in periods.items():
        previous=periods.get(str(int(key[:4])-1)+key[4:])
        row['yoy']={}
        if previous:
            for field,value in row['values'].items():
                old=previous['values'].get(field)
                # Negative/zero bases are not rendered as percentage growth.
                if value is not None and old is not None and Decimal(old)>0:
                    row['yoy'][field]=str((Decimal(value)-Decimal(old))/Decimal(old)*100)
    return sorted(periods.values(),key=lambda r:r['period'],reverse=True)[:12]

def refresh(storage,key,code,exchange,client=None,expected_name=None):
    if not re.fullmatch(r'\d{6}',str(code)) or exchange not in ('sz','sh','bj'):raise FinancialError('目前支持A股，请填写6位证券代码并选择交易所')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',key):raise FinancialError('公司标识无效')
    profile=f'https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/stockid/{code}/displaytype/4.phtml'
    with LOCK:
        own=client is None
        client=client or httpx.Client(timeout=25,follow_redirects=False)
        try:
            # The quote feed verifies exchange+code, not just the numeric code.
            quote=client.get('https://qt.gtimg.cn/q='+exchange+code)
            quote.raise_for_status();quote.encoding='gb18030'
            pieces=quote.text.split('~')
            if not quote.text.startswith('v_'+exchange+code+'=') or len(pieces)<4 or pieces[2]!=code:raise FinancialError('证券代码或交易所不匹配')
            company_name=pieces[1]
            if expected_name:
                from .securities import normalized
                if normalized(company_name)!=normalized(expected_name):raise FinancialError('数据源返回名称与证券目录不一致，请更新目录或人工核对')
            raw={}
            for statement in FIELDS:
                r=client.get(ENDPOINT,params={'paperCode':exchange+code,'source':statement,'type':'0','page':'1','num':'16'})
                r.raise_for_status();raw[statement]=r.json()
            rows=parse_statements(raw)
            result={'provider':'新浪财经','identity_provider':'腾讯证券报价标识','company_name':company_name,'code':code,'exchange':exchange,'fetched_at':now_iso(),'source_url':profile,'endpoint':ENDPOINT,'unit':'元','display_unit':'亿元','scope':'人民币合并报表；利润与现金流为年初至报告期末累计，资产负债为期末值','periods':rows}
            atomic_write_json(storage.path(f'derived/financials/raw/{key}/{now_iso().replace(":","-")}.json'),{'fetched_at':result['fetched_at'],'code':code,'exchange':exchange,'responses':raw})
            atomic_write_json(storage.path(f'derived/financials/{key}.json'),result)
            return result
        except FinancialError:raise
        except (httpx.HTTPError,ValueError,KeyError,TypeError):raise FinancialError('财务数据源暂不可用，保留上次成功数据，请稍后重试') from None
        finally:
            if own:client.close()
