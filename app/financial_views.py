"""Deterministic comparable-period views and local SVG trends."""
import html
import math
from decimal import Decimal

PERIODS={'latest':'同最新报告期跨年比较','annual':'年报（全年）','h1':'中报（上半年）','q3':'三季报（前三季度）','q1':'一季报','all':'全部累计报告期'}
ENDS={'annual':'12-31','h1':'06-30','q3':'09-30','q1':'03-31'}

def periods(rows,mode='latest'):
    if mode not in PERIODS:raise ValueError('报告期筛选无效')
    if mode=='all':return rows
    ending=rows[0]['period'][5:] if mode=='latest' and rows else ENDS.get(mode,'')
    return [row for row in rows if row['period'][5:]==ending]

def trend(rows,metric,label):
    points=[]
    for row in reversed(rows):
        value=row.get('values',{}).get(metric)
        try:number=float(Decimal(value)/Decimal(100000000)) if value is not None else None
        except (ValueError,TypeError,OverflowError):number=None
        if number is not None and not math.isfinite(number):number=None
        points.append((row['period'],number))
    valid=[v for _,v in points if v is not None]
    if not valid:return ''
    low=min(min(valid),0);high=max(max(valid),0)
    if high==low:high=low+1
    margin=(high-low)*.12;low-=margin;high+=margin
    def y(v):return 205-(v-low)/(high-low)*165
    def x(i):return 70+(i/(max(1,len(points)-1)))*670
    title=html.escape(label+'趋势（亿元）；利润和现金流为累计，资产负债为期末值')
    svg=[f'<svg viewBox="0 0 800 260" role="img" aria-label="{title}" xmlns="http://www.w3.org/2000/svg"><title>{title}</title><rect width="800" height="260" fill="#fff"/>']
    for fraction in [0,.25,.5,.75,1]:
        value=low+(high-low)*fraction;axis=y(value)
        svg.append(f'<line x1="65" x2="750" y1="{axis:.2f}" y2="{axis:.2f}" stroke="#e7ece8"/><text x="58" y="{axis+4:.2f}" text-anchor="end" fill="#77867f" font-size="11">{value:,.1f}</text>')
    segments=[];current=[]
    for i,(date,value) in enumerate(points):
        if value is None:
            if current:segments.append(current)
            current=[]
        else:current.append((x(i),y(value)))
    if current:segments.append(current)
    for segment in segments:
        if len(segment)>1:svg.append('<polyline points="'+' '.join(f'{px:.2f},{py:.2f}' for px,py in segment)+'" fill="none" stroke="#4a8069" stroke-width="2.4"/>')
    for i,(date,value) in enumerate(points):
        if value is not None:svg.append(f'<circle cx="{x(i):.2f}" cy="{y(value):.2f}" r="4" fill="#4a8069"><title>{html.escape(date)}：{value:,.2f}亿元</title></circle>')
        if len(points)<=6 or i%2==0 or i==len(points)-1:svg.append(f'<text x="{x(i):.2f}" y="232" text-anchor="middle" fill="#77867f" font-size="11">{html.escape(date[:7])}</text>')
    svg.append('</svg>')
    return ''.join(svg)
