import os
import json
import base64
import meeting_database as db
from pathlib import Path
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

OUTPUT_DIR = Path("meeting_outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

def safe_text(txt):
    if not txt: return ""
    result = []
    for c in str(txt):
        if ord(c) < 128:
            result.append(c)
        else:
            result.append(' ')
    return ''.join(result).strip()

def generate_transcript_pdf(meeting_id, transcript_json, title="Meeting"):
    filename = f"Transcripts_{meeting_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf_path = OUTPUT_DIR / filename
    
    try:
        PAGE_W, PAGE_H = letter
        MARGIN = 0.75 * inch
        CONTENT_W = PAGE_W - 2 * MARGIN
        doc = SimpleDocTemplate(str(pdf_path), pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN)
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle('RTitle', parent=styles['Heading1'], alignment=1, fontSize=22, spaceAfter=8, textColor=colors.HexColor("#2563eb"))
        h2_style = ParagraphStyle('RH2', parent=styles['Heading2'], fontSize=14, spaceBefore=20, spaceAfter=8, textColor=colors.HexColor("#1e40af"), borderPadding=4, borderSide="bottom", borderWidth=0.5, borderColor=colors.HexColor("#bfdbfe"))
        normal_style = ParagraphStyle('RNormal', parent=styles['Normal'], fontSize=10, leading=15, textColor=colors.HexColor("#334155"))
        cell_style = ParagraphStyle('RCell', parent=styles['Normal'], fontSize=9, leading=13, textColor=colors.HexColor("#475569"))

        elements = []
        header_table_data = [[
            Paragraph(safe_text("RENATA TRANSCRIPT"), ParagraphStyle('BName', parent=title_style, alignment=0, fontSize=20)),
            Paragraph(f"Meeting ID: {meeting_id}<br/>Generated: {datetime.now().strftime('%B %d, %Y')}", ParagraphStyle('RDate', parent=normal_style, alignment=2, fontSize=9))
        ]]
        header_table = Table(header_table_data, colWidths=[CONTENT_W*0.7, CONTENT_W*0.3])
        header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'BOTTOM'), ('BOTTOMPADDING', (0,0), (-1,-1), 12)]))
        elements.append(header_table)
        
        elements.append(Table([[""]], colWidths=[CONTENT_W], rowHeights=[2], style=TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#2563eb"))])))
        elements.append(Spacer(1, 18))

        structured_transcript = []
        if transcript_json:
            try:
                structured_transcript = json.loads(transcript_json)
            except:
                pass

        if structured_transcript:
            elements.append(Paragraph("Full Transcript", h2_style))
            trans_data = [["Time", "Speaker", "Text"]]
            for s in structured_transcript:
                trans_data.append([
                    Paragraph(safe_text(s.get('timestamp','')), cell_style),
                    Paragraph(safe_text(s.get('speaker','')), ParagraphStyle('RSpeak', parent=cell_style, fontName='Helvetica-Bold')),
                    Paragraph(safe_text(s.get('text','')), normal_style)
                ])
            t = Table(trans_data, colWidths=[CONTENT_W*0.12, CONTENT_W*0.18, CONTENT_W*0.7])
            t.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0),colors.HexColor("#f8fafc")), 
                ('TEXTCOLOR',(0,0),(-1,0),colors.HexColor("#475569")),
                ('GRID',(0,0),(-1,-1),0.1,colors.HexColor("#e2e8f0")),
                ('VALIGN',(0,0),(-1,-1),'TOP'),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ]))
            elements.append(t)
        else:
            elements.append(Paragraph("No structured transcript available.", normal_style))

        doc.build(elements)
        print(f"Generated {pdf_path}")
        return pdf_path
    except Exception as e:
        print(f"Failed to generate PDF: {e}")
        return None

def fix_all_missing():
    print(">>> Fixing missing Transcript PDFs for existing meetings...")
    meetings = db.fetch_all("SELECT meeting_id, title, transcript_text FROM meetings WHERE transcripts_pdf_blob IS NULL AND transcript_text IS NOT NULL")
    
    for m in meetings:
        m_id = m['meeting_id']
        print(f"Processing {m_id}...")
        pdf_path = generate_transcript_pdf(m_id, m['transcript_text'], m['title'])
        if pdf_path:
            with open(pdf_path, "rb") as f:
                blob = base64.b64encode(f.read()).decode('utf-8')
            
            # Update DB with both path and blob
            db.exec_commit("UPDATE meetings SET transcripts_pdf_path = ?, transcripts_pdf_blob = ? WHERE meeting_id = ?", 
                           (str(pdf_path), blob, m_id))
            print(f"Uploaded transcript blob for {m_id}")

if __name__ == "__main__":
    fix_all_missing()
