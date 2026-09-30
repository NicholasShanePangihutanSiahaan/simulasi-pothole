#!/usr/bin/env python3
"""Build the Indonesian exhibition guide with local fonts and ReportLab."""
from pathlib import Path
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, Image, KeepTogether, Preformatted, HRFlowable)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon

ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs'


def build():
    for name,file in [('Body','DejaVuSans.ttf'),('Bold','DejaVuSans-Bold.ttf'),('Mono','DejaVuSansMono.ttf')]:
        pdfmetrics.registerFont(TTFont(name,'/usr/share/fonts/truetype/dejavu/'+file))
    pdfmetrics.registerFontFamily('Body',normal='Body',bold='Bold',italic='Body',boldItalic='Bold')
    dark=colors.HexColor('#142c2a')
    green=colors.HexColor('#277a62')
    muted=colors.HexColor('#526762')
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BodyID',fontName='Body',fontSize=9.4,leading=15,spaceAfter=8,textColor=dark))
    styles.add(ParagraphStyle(name='SmallID',fontName='Body',fontSize=8,leading=12,spaceAfter=8,textColor=muted))
    styles.add(ParagraphStyle(name='TitleID',fontName='Bold',fontSize=30,leading=37,spaceAfter=15,textColor=dark))
    styles.add(ParagraphStyle(name='H1ID',fontName='Bold',fontSize=16,leading=22,spaceBefore=15,spaceAfter=10,textColor=green,keepWithNext=True))
    styles.add(ParagraphStyle(name='H2ID',fontName='Bold',fontSize=11,leading=16,spaceBefore=10,spaceAfter=6,textColor=dark,keepWithNext=True))
    styles.add(ParagraphStyle(name='CellID',fontName='Body',fontSize=8,leading=11,textColor=dark))
    styles.add(ParagraphStyle(name='CodeID',fontName='Mono',fontSize=7.5,leading=11,spaceBefore=5,spaceAfter=9,
                              backColor=colors.HexColor('#edf2ef'),borderPadding=10))
    def markup(s):
        s=escape(s)
        s=re.sub(r'`([^`]+)`',r'<font name="Mono">\1</font>',s)
        s=re.sub(r'\*\*([^*]+)\*\*',r'<b>\1</b>',s)
        return s
    def para(s,style='BodyID'):
        return Paragraph(markup(s),styles[style])
    story=[]
    story += [Spacer(1,25),para('CAPSTONE B-08  /  DTETI FT UGM  /  2026','SmallID'),
              para('Jaga Jalan<br/>Panduan simulasi'.replace('<br/>','\n'),'TitleID')]
    # Explicit HTML line break only for the cover.
    story[-1]=Paragraph('Jaga Jalan<br/>Panduan simulasi',styles['TitleID'])
    story += [para('Deteksi jalan rusak berbasis IMU dan vision\nuntuk pengendara sepeda.'),Spacer(1,12)]
    screenshot=DOC/'images/dashboard.png'
    if screenshot.exists():
        from PIL import Image as PILImage
        with PILImage.open(screenshot) as img:
            iw,ih=img.size
        story.append(Image(str(screenshot),width=505,height=505*ih/iw))
    story += [Spacer(1,14),para('Jalankan: bash start.sh   ·   Buka: http://localhost:8765','H2ID'),
              para('Klik Aktifkan suara, tunggu kalibrasi, lalu gunakan W/A/S/D atau stik PS.\nPanduan ini mencakup skenario pagelaran, alur data, parameter, dan pemecahan masalah.','SmallID'),
              HRFlowable(width='100%',thickness=1,color=colors.HexColor('#c8d8cf')),Spacer(1,10),
              para('Edisi 30 September 2026. Berdasarkan proposal C-251 B-08 revisi 01.\nSimulasi memakai Gazebo Harmonic dan detektor OpenCV sebagai baseline; bobot FOMO belum disertakan.','SmallID'),PageBreak()]
    story.append(para('Arsitektur demonstrasi','H1ID'))
    d=Drawing(505,230)
    rows=[('IMU + GPS','Simpan lokal','HTTP ke server'),
          ('Kamera depan','Detektor citra','Buzzer + LED'),
          ('Cache dari server','Posisi + arah/jalur','Buzzer + LED')]
    for row,labels in enumerate(rows):
        y=172-row*66
        for col,label in enumerate(labels):
            x=col*172
            d.add(Rect(x,y,158,43,rx=6,ry=6,fillColor=colors.HexColor('#edf3ef'),strokeColor=colors.HexColor('#b9cec3')))
            d.add(String(x+79,y+18,label,fontName='Bold',fontSize=8.5,textAnchor='middle',fillColor=dark))
            if col<2:
                d.add(Line(x+159,y+21,x+170,y+21,strokeColor=green))
                d.add(Polygon([x+170,y+21,x+165,y+24,x+165,y+18],fillColor=green,strokeColor=green))
    story += [d,para('Penyimpanan perangkat dan server dipisahkan. Saat offline, temuan IMU tetap masuk antrean lokal; peringatan peta memakai cache terakhir. Keputusan vision menggunakan piksel kamera.','BodyID'),
              para('Isi panduan','H1ID')]
    headings=[line[3:] for line in (DOC/'Panduan_Simulasi.md').read_text().splitlines() if line.startswith('## ')]
    for h in headings:
        story.append(para(h,'SmallID'))
    story.append(PageBreak())
    lines=(DOC/'Panduan_Simulasi.md').read_text().splitlines()
    i=0
    while i<len(lines):
        line=lines[i]
        if not line.strip() or line.startswith('# '):
            i+=1;continue
        if line.startswith('## '):
            story.append(para(line[3:],'H1ID'));i+=1;continue
        if line.startswith('### '):
            story.append(para(line[4:],'H2ID'));i+=1;continue
        if line.startswith('```'):
            code=[];i+=1
            while i<len(lines) and not lines[i].startswith('```'):
                code.append(lines[i]);i+=1
            story.append(Preformatted('\n'.join(code),styles['CodeID'],maxLineLength=93))
            i+=1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].startswith('|'):
                cells=[c.strip() for c in lines[i].strip('|').split('|')]
                if not all(re.fullmatch(r'[-: ]+',c) for c in cells):
                    rows.append([para(c,'CellID') for c in cells])
                i+=1
            widths=[170,335] if len(rows[0])==2 else [145,180,180]
            table=Table(rows,colWidths=widths,repeatRows=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#d8e7df')),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#f5f7f5'),colors.white]),
                ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),
                ('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),
                ('BOTTOMPADDING',(0,0),(-1,-1),7),
                ('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#97b9a9'))]))
            story += [table,Spacer(1,10)];continue
        if line.startswith('- ') or re.match(r'^\d+\. ',line):
            story.append(para(line));i+=1;continue
        parts=[line];i+=1
        while i<len(lines) and lines[i].strip() and not lines[i].startswith(('#','|','```','- ')) and not re.match(r'^\d+\. ',lines[i]):
            parts.append(lines[i]);i+=1
        story.append(para(' '.join(parts)))
    def decoration(canvas,doc):
        canvas.saveState()
        width,height=A4
        canvas.setStrokeColor(colors.HexColor('#d5dfd7'))
        canvas.line(45,40,width-45,40)
        canvas.setFont('Body',7)
        canvas.setFillColor(muted)
        canvas.drawString(45,27,'JAGA JALAN  /  CAPSTONE B-08  /  PANDUAN DEMONSTRASI')
        canvas.drawRightString(width-45,27,str(doc.page))
        canvas.restoreState()
    pdf=DOC/'Panduan_Simulasi_Capstone_B08.pdf'
    document=SimpleDocTemplate(str(pdf),pagesize=A4,rightMargin=45,leftMargin=45,topMargin=40,bottomMargin=53,
        title='Panduan Simulasi Capstone B-08 — Jaga Jalan',author='Capstone B-08',subject='Simulasi Gazebo IMU vision GPS dan buzzer')
    document.build(story,onFirstPage=decoration,onLaterPages=decoration)
    print(pdf)


if __name__=='__main__':
    build()
