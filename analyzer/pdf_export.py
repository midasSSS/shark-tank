"""Create a clean PDF export from an investment memo."""
import re
from html import escape
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


def _fonts():
    regular = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    bold = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
    if regular.exists() and bold.exists():
        if "InvestmentArial" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("InvestmentArial", str(regular)))
            pdfmetrics.registerFont(TTFont("InvestmentArial-Bold", str(bold)))
        return "InvestmentArial", "InvestmentArial-Bold"
    return "Helvetica", "Helvetica-Bold"


def _inline(text):
    text = escape(text.strip()).replace("**", "")
    return re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", text)


def memo_pdf(title: str, date: str, markdown: str) -> bytes:
    regular, bold = _fonts()
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=LETTER, rightMargin=.72 * inch,
        leftMargin=.72 * inch, topMargin=.7 * inch, bottomMargin=.65 * inch,
        title=title, author="Investment Analyzer")
    base = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=base["BodyText"], fontName=regular,
        fontSize=9.5, leading=15, textColor=colors.HexColor("#242424"), spaceAfter=9)
    styles = {
        1: ParagraphStyle("H1", parent=body, fontName=bold, fontSize=22, leading=27,
                          textColor=colors.HexColor("#111111"), spaceAfter=12),
        2: ParagraphStyle("H2", parent=body, fontName=bold, fontSize=14, leading=18,
                          textColor=colors.HexColor("#111111"), spaceBefore=13, spaceAfter=8),
        3: ParagraphStyle("H3", parent=body, fontName=bold, fontSize=11, leading=15,
                          textColor=colors.HexColor("#181818"), spaceBefore=9, spaceAfter=6),
    }
    meta = ParagraphStyle("Meta", parent=body, fontSize=8, textColor=colors.HexColor("#707070"))
    bullet = ParagraphStyle("Bullet", parent=body, leftIndent=14, firstLineIndent=-8, bulletIndent=0)
    story = [Paragraph(_inline(title), styles[1]), Paragraph(f"Analyzed {escape(date)}", meta), Spacer(1, 12)]
    for raw in markdown.replace("\u2011", "-").splitlines():
        line = raw.strip()
        if not line or line == "---":
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            story.append(Paragraph(_inline(heading.group(2)), styles[len(heading.group(1))]))
        elif re.match(r"^[-*]\s+", line):
            story.append(Paragraph(_inline(re.sub(r"^[-*]\s+", "", line)), bullet, bulletText="-"))
        elif re.match(r"^\d+\.\s+", line):
            number, text = line.split(".", 1)
            story.append(Paragraph(_inline(text), bullet, bulletText=number + "."))
        else:
            story.append(Paragraph(_inline(line), body))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 7.5)
        canvas.setFillColor(colors.HexColor("#808080"))
        canvas.drawString(.72 * inch, .34 * inch, "Investment Analyzer")
        canvas.drawRightString(LETTER[0] - .72 * inch, .34 * inch, str(doc.page))
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def legacy_parts(markdown: str, fallback_title: str, fallback_date: str):
    lines = markdown.splitlines()
    title, date, consumed = fallback_title, fallback_date, set()
    for index, line in enumerate(lines[:8]):
        if line.startswith("# "):
            title = re.sub(r"^#\s+(?:Investment Memo:\s*)?", "", line).strip()
            consumed.add(index)
        match = re.match(r"\*\*Date:\*\*\s*(.+)", line.strip())
        if match:
            date = match.group(1).strip()
            consumed.add(index)
    remaining = "\n".join(line for index, line in enumerate(lines) if index not in consumed).lstrip("\n- ")
    return title, date, remaining
