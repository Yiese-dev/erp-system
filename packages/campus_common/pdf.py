from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TEAL = colors.HexColor("#00695F")
CORAL = colors.HexColor("#B44C3B")
INK = colors.HexColor("#243134")
MIST = colors.HexColor("#F3F6F5")
LINE = colors.HexColor("#D5DEDB")

styles = getSampleStyleSheet()
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK)
HEADING = ParagraphStyle("Heading", parent=BODY, fontName="Helvetica-Bold", fontSize=12, leading=16, spaceBefore=8, spaceAfter=4, textColor=TEAL)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=8.5, leading=11)


def money(amount: int | float) -> str:
    return f"{int(round(amount)):,}".replace(",", " ") + " FCFA"


def render_pdf(title: str, institution: str, subtitle: str, blocks: list[tuple], generated_at: datetime) -> bytes:
    """blocks: ("heading", text) | ("text", text) | ("kv", [(label, value)]) | ("table", header, rows)."""
    buffer = BytesIO()

    def frame(canvas, document):
        canvas.saveState()
        width, height = A4
        canvas.setFillColor(TEAL)
        canvas.rect(0, height - 26 * mm, width, 26 * mm, fill=1, stroke=0)
        canvas.setFillColor(CORAL)
        canvas.rect(0, height - 27.2 * mm, width, 1.2 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 14)
        canvas.drawString(18 * mm, height - 12 * mm, institution)
        canvas.setFont("Helvetica", 9)
        canvas.drawString(18 * mm, height - 18.5 * mm, f"Campus ERP  |  {title}")
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(18 * mm, 10 * mm, f"Generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}  |  Official system record")
        canvas.drawRightString(width - 18 * mm, 10 * mm, f"Page {document.page}")
        canvas.restoreState()

    story = [Paragraph(escape(title), ParagraphStyle("Title", parent=HEADING, fontSize=16, leading=20, spaceBefore=0)),
             Paragraph(escape(subtitle), BODY), Spacer(1, 4 * mm)]
    for block in blocks:
        kind = block[0]
        if kind == "heading":
            story.append(Paragraph(escape(block[1]), HEADING))
        elif kind == "text":
            story.append(Paragraph(escape(block[1]), BODY))
        elif kind == "kv":
            table = Table([[Paragraph(f"<b>{escape(str(label))}</b>", CELL), Paragraph(escape(str(value)), CELL)] for label, value in block[1]],
                          colWidths=[55 * mm, 115 * mm])
            table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(table)
        elif kind == "table":
            header, rows = block[1], block[2]
            data = [[Paragraph(f"<b>{escape(str(cell))}</b>", ParagraphStyle("Head", parent=CELL, textColor=colors.white)) for cell in header]]
            data += [[Paragraph(escape(str(cell)), CELL) for cell in row] for row in rows]
            if not rows:
                data.append([Paragraph("No records for this period.", CELL)] + [""] * (len(header) - 1))
            table = Table(data, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), TEAL),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, MIST]),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(table)
        story.append(Spacer(1, 3 * mm))
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                                 topMargin=34 * mm, bottomMargin=18 * mm, title=title, author=institution)
    document.build(story, onFirstPage=frame, onLaterPages=frame)
    return buffer.getvalue()
