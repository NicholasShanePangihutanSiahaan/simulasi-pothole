#!/usr/bin/env python3
"""Make review figures, machine summary and a PDF from the IMU field-test notes."""
import json
from pathlib import Path
import re
from xml.sax.saxutils import escape
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,PageBreak
from reportlab.lib.units import mm

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/imu-characterisation'
DOC=ROOT/'docs'
LABELS={'flat':'Aspal mulus','bump':'Polisi tidur','paving':'Paving',
        'pothole_A':'Pothole A','pothole_C':'Pothole C','curve':'Tikungan oval',
        'slalom':'Manuver agresif','slalom_centered':'Slalom terpusat'}


def main():
    images=DOC/'images';images.mkdir(exist_ok=True)
    rows=[]
    for directory in (DATA,DATA/'followups'):
        for file in sorted(directory.glob('*.json')):
            if file.name=='summary.json':continue
            d=json.loads(file.read_text());r=dict(d['summary'])
            candidates=[s for s in d['snapshots'] if s['imu'].get('assessment')]
            strong=[s for s in candidates if s['imu']['assessment']['checks']['amplitude']]
            if candidates:
                best=max(strong or candidates,key=lambda s:sum(s['imu']['assessment']['checks'].values()))
                r['closest_polled_pattern']={'time':best['time'],'x':best['pose']['x'],
                    'assessment':best['imu']['assessment'],
                    'missing':[k for k,v in best['imu']['assessment']['checks'].items() if not v]}
            r['evidence']=str(file.relative_to(ROOT))
            r['followup']=directory.name=='followups'
            rows.append(r)
    (DOC/'imu-characterisation-summary.json').write_text(json.dumps({'cases':rows,
        'note':'Confirmation markers use 100 Hz history; feature snapshots are sampled by HTTP polling, so transient passing gates can be missed.'},indent=2))

    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9})
    fig,axes=plt.subplots(2,2,figsize=(10.5,6),constrained_layout=True)
    for ax,name in zip(axes.flat,['bump','paving','curve','slalom']):
        d=json.loads((DATA/f'{name}-6.json').read_text());h=d['imu_history'];t0=h[0][0]
        ax.plot([p[0]-t0 for p in h],[p[1] for p in h],color='#277a62',lw=.8)
        ax.axhline(4.5,color='#b67224',ls='--',lw=.8);ax.axhline(-4.5,color='#b67224',ls='--',lw=.8)
        ax.set_title(LABELS[name]+f" | puncak {d['summary']['peak_abs_az']:.2f} m/s²")
        ax.set_xlabel('Waktu sejak mulai berkendara (s)');ax.set_ylabel('aZ tersaring (m/s²)');ax.grid(alpha=.2)
    fig.suptitle('Target 6 m/s: guncangan melampaui garis bukan keputusan pothole\nManuver agresif sempat keluar lintasan; kecepatan aktual berubah saat berbelok.',fontsize=11)
    fig.savefig(images/'imu-characterisation-high-speed.png',dpi=180);plt.close(fig)

    d=json.loads((DATA/'pothole_C-1.5.json').read_text());h=d['imu_history']
    peak=max(h,key=lambda p:abs(p[1]));origin=peak[0]
    fig,axes=plt.subplots(3,1,figsize=(10,6.5),sharex=True,constrained_layout=True)
    axes[0].plot([p[0]-origin for p in h],[p[1] for p in h],color='#277a62',lw=1)
    axes[0].axhline(4.5,color='#b67224',ls='--');axes[0].axhline(-4.5,color='#b67224',ls='--')
    axes[0].set_ylabel('aZ (m/s²)')
    rows=d['snapshots'];pitch=[r['pose']['pitch']*180/3.141592653589793 for r in rows]
    axes[1].plot([r['time']-origin for r in rows],pitch,color='#3569a6');axes[1].set_ylabel('Pitch (derajat)')
    a=[r for r in rows if r['imu'].get('assessment')]
    axes[2].plot([r['time']-origin for r in a],[r['imu']['assessment']['descent_integral']*1000 for r in a],'.-',color='#8c4c83',ms=3)
    axes[2].axhline(-12,color='#b67224',ls='--');axes[2].set_ylabel('Integral minimum\nkandidat (mm)');axes[2].set_xlabel('Waktu relatif terhadap puncak guncangan (s)')
    for ax in axes:ax.set_xlim(-.7,1.7);ax.grid(alpha=.2)
    fig.suptitle('Pothole C, target 1,5 m/s: lubang nyata terlewat pada lintasan pertama\nSaat benturan naik, fitur integral penurunan belum memenuhi syarat. Integral ini bukan kedalaman lubang.',fontsize=11)
    fig.savefig(images/'imu-characterisation-missed-hole.png',dpi=180);plt.close(fig)

    source=DOC/'Analisis_Definisi_Lubang_IMU.md'
    if not source.exists():return
    for name,file in [('Body','DejaVuSans.ttf'),('Bold','DejaVuSans-Bold.ttf')]:
        pdfmetrics.registerFont(TTFont(name,'/usr/share/fonts/truetype/dejavu/'+file))
    pdfmetrics.registerFontFamily('Body',normal='Body',bold='Bold',italic='Body',boldItalic='Bold')
    body=ParagraphStyle('body',fontName='Body',fontSize=9,leading=13,spaceAfter=7)
    title=ParagraphStyle('title',parent=body,fontName='Bold',fontSize=18,leading=24,spaceAfter=14)
    heading=ParagraphStyle('heading',parent=body,fontName='Bold',fontSize=12,leading=17,spaceBefore=10,keepWithNext=True)
    small=ParagraphStyle('small',parent=body,fontSize=7.7,leading=11)
    story=[];table=[]
    def para(text,style=body):
        return Paragraph(re.sub(r'\*\*(.*?)\*\*',r'<b>\1</b>',escape(text).replace('`','')),style)
    def flush():
        if not table:return
        cells=[[para(c,small) for c in row] for row in table]
        t=Table(cells,colWidths=[170*mm/len(table[0])]*len(table[0]),repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e3e8d9')),('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#bdc7bd')),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5)]))
        story.extend([t,Spacer(1,8)]);table.clear()
    for line in source.read_text().splitlines():
        if line.startswith('|'):
            cells=[s.strip() for s in line.strip('|').split('|')]
            if not all(re.fullmatch(r'[:\- ]+',s) for s in cells):table.append(cells)
            continue
        flush()
        if line.startswith('# '):story.append(para(line[2:],title))
        elif line.startswith('## '):story.append(para(line[3:],heading))
        elif line.strip():story.append(para(line))
    flush()
    for filename in ['imu-characterisation-high-speed.png','imu-characterisation-missed-hole.png']:
        story.append(PageBreak())
        from PIL import Image as PILImage
        w,h=PILImage.open(images/filename).size
        story.append(Image(str(images/filename),width=175*mm,height=175*mm*h/w))
    SimpleDocTemplate(str(DOC/'Analisis_Definisi_Lubang_IMU.pdf'),pagesize=(210*mm,297*mm),
                      leftMargin=18*mm,rightMargin=18*mm,topMargin=18*mm,bottomMargin=18*mm,
                      title='Analisis definisi lubang dan pengujian IMU Gazebo',author='Capstone B-08').build(story)
    print('Created IMU analysis summary, figures and PDF.')


if __name__=='__main__':main()
