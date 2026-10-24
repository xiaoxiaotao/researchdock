"""Conservative comparison keys; source labels and quotations remain unchanged."""
import re
from decimal import Decimal, InvalidOperation


def period_key(raw, published_year):
    value=re.sub(r'\s+','',raw).upper()
    match=re.match(r'^(20\d{2}|\d{2})(.*)$',value)
    if not match:
        return None
    year,tail=match.groups()
    year=int(year)
    if year<100:
        if not published_year:
            return None
        year=(published_year//100)*100+year
        if abs(year-published_year)>10:
            return None
    tail=tail.removeprefix('年')
    quarter={'第一季度':'Q1','一季度':'Q1','第二季度':'Q2','二季度':'Q2','第三季度':'Q3','三季度':'Q3','第四季度':'Q4','四季度':'Q4',
             '前三季度':'YTDQ3','前三季':'YTDQ3','1-9月':'YTDQ3','Q1-3':'YTDQ3','Q1-Q3':'YTDQ3',
             '上半年':'H1','1-6月':'H1','Q1-2':'H1','Q1-Q2':'H1','下半年':'H2','全年':'FY','年度':'FY','':'FY'}
    tail=quarter.get(tail,tail)
    if tail not in {'Q1','Q2','Q3','Q4','YTDQ3','H1','H2','FY'}:
        return None
    return f'{year}{tail}'


def comparison_key(item, published_year):
    if not all(item.get(k) for k in ('metric','period','unit','value','kind')) or not re.search(r'[0-9]',item['value']):
        return None
    period=period_key(item['period'],published_year)
    if not period:
        return None
    aliases={'营收':'营业收入','营业收入':'营业收入','归母净利':'归母净利润','归母净利润':'归母净利润','扣非归母净利':'扣非归母净利润','扣非归母净利润':'扣非归母净利润','PE':'市盈率','市盈率':'市盈率'}
    metric=aliases.get(item['metric'].upper(),item['metric'])
    unit=item['unit'].replace('％','%')
    if metric=='市盈率' and unit.upper() in {'X','倍'}:
        unit='倍'
    if unit.upper() in {'GW','MW','GWH','MWH'}:
        unit=unit.upper()
    return [metric,period,unit,item['kind']]


def different_value(a,b):
    try:
        return Decimal(a)!=Decimal(b)
    except InvalidOperation:
        return a!=b
