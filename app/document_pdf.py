"""Local, version-pinned PDF export. Never calls a model or downloads remote assets."""
import hashlib
import os
import re
import tempfile
import threading
from html import escape
from pathlib import Path
from .frontmatter import split_frontmatter
from .utils import sha256_text

FONT_LOCK=threading.Lock()
VERSION='1'


def font_name():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    with FONT_LOCK:
        if 'KBUnicode' in pdfmetrics.getRegisteredFontNames():return 'KBUnicode'
        path=Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
        if path.exists():
            pdfmetrics.registerFont(TTFont('KBUnicode',str(path)))
            return 'KBUnicode'
        if 'STSong-Light' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        return 'STSong-Light'


def export(storage,document_id,revision=None):
    if not re.fullmatch(r'doc_[0-9A-Z]{26}',document_id):raise ValueError('资料编号无效')
    manifest=storage.read_manifest(document_id)
    if not manifest:raise FileNotFoundError('资料不存在')
    revision=revision or manifest['current_revision']
    target=next((r for r in manifest['revisions'] if r['revision']==revision),None)
    if not target:raise FileNotFoundError('版本不存在')
    raw=storage.read_revision_text(target['archive_path'])
    meta,body=split_frontmatter(raw)
    # Only local images already archived by the reader are eligible for embedding.
    from .youdao import image_links
    images={}
    for url in image_links(body):
        match=re.search(r'/resource/([a-f0-9]{32})/',url)
        if match:
            path=storage.path(f'cache/youdao-images/{match[1]}/{hashlib.sha256(url.encode()).hexdigest()}')
            if path.is_file():images[url]=path
    source_images=[]
    for item in meta.get('source_attachments') or []:
        image_id=item.get('image_id','')
        if item.get('kind')=='image' and re.fullmatch(r'\d+',str(image_id)):
            path=storage.path(f'cache/source-images/{document_id}-r{revision}-{image_id}.bin')
            if path.is_file():source_images.append(path)
    fingerprint=sha256_text(VERSION+raw+'|'.join(str(p)+str(p.stat().st_size) for p in [*images.values(),*source_images]))
    output=storage.path(f'cache/document-pdfs/{document_id}/r{revision}-{fingerprint[:24]}.pdf')
    title=str(meta.get('title') or '研究资料')
    filename=re.sub(r'[\\/:*?"<>|\x00-\x1f]','_',title)[:100]+f'-r{revision}.pdf'
    if output.is_file():return output,filename

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Image,HRFlowable
    font=font_name();width,height=A4;usable=width-96
    normal=ParagraphStyle('body',fontName=font,fontSize=10.5,leading=17,spaceAfter=9,wordWrap='CJK',splitLongWords=True)
    heading=ParagraphStyle('heading',parent=normal,fontSize=14,leading=21,spaceBefore=14,spaceAfter=10,keepWithNext=True)
    title_style=ParagraphStyle('title',parent=heading,fontSize=20,leading=29,spaceAfter=16)
    small=ParagraphStyle('meta',parent=normal,fontSize=8.5,leading=14,textColor=colors.HexColor('#656565'))
    story=[Paragraph(escape(title),title_style)]
    source=meta.get('source') or {}
    for text in [f"来源：{source.get('space_name') or source.get('platform') or '未知'}　版本：r{revision}",f"发布时间：{meta.get('published_at') or '未知'}",f"原文链接：{source.get('url') or '无'}",'导出范围：归档正文及已缓存图片。PDF、音频等附件原件请在资料页另行下载。']:
        story.append(Paragraph(escape(text),small))
    story.extend([HRFlowable(width='100%',color=colors.HexColor('#dddddd')),Spacer(1,14)])
    def add_image(path):
        try:
            img=Image(str(path));scale=min(usable/img.imageWidth,520/img.imageHeight,1)
            img.drawWidth=img.imageWidth*scale;img.drawHeight=img.imageHeight*scale
            story.extend([img,Spacer(1,12)])
        except Exception:story.append(Paragraph('图片暂无法嵌入，请查看原件。',small))
    for block in re.split(r'\n\s*\n',body):
        block=block.strip()
        if not block:continue
        match=re.fullmatch(r'!\[[^\]]*\]\((https?://[^\s)]+)\)',block)
        if match:
            url=match[1]
            if url in images:add_image(images[url])
            else:story.append(Paragraph('原图未缓存，查看原笔记：'+escape(url),small))
        elif re.fullmatch(r'[-*_]{3,}',block):story.append(HRFlowable(width='100%',color=colors.HexColor('#dddddd')))
        elif re.match(r'^#{1,6}\s',block):story.append(Paragraph(escape(re.sub(r'^#{1,6}\s+','',block)),heading))
        else:story.append(Paragraph(escape(block).replace('\n','<br/>'),normal))
    for path in source_images:add_image(path)
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont(font,8);canvas.setFillColor(colors.HexColor('#777777'))
        canvas.drawString(48,28,'股票研究知识库 · 归档正文导出')
        canvas.drawRightString(width-48,28,str(doc.page));canvas.restoreState()
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=output.parent,suffix='.pdf');os.close(fd)
    try:
        SimpleDocTemplate(tmp,pagesize=A4,rightMargin=48,leftMargin=48,topMargin=44,bottomMargin=48,title=title,author='股票研究知识库').build(story,onFirstPage=footer,onLaterPages=footer)
        os.replace(tmp,output)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return output,filename
