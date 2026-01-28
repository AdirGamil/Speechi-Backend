"""
Document generation service.

Builds Word (.docx) and PDF documents from meeting transcript and analysis.
Single source of content, multiple output formats.
No AI usage; consumes transcript and AnalysisResult only.

Features:
- Language-aware section headings
- RTL support for Hebrew and Arabic
- Clean, professional typography
"""

import os
import tempfile
from datetime import datetime

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.models.schemas import ActionItem, AnalysisResult
from app.utils import file_utils
from app.utils.document_labels import get_labels, is_rtl, DocumentLabels


def _format_action_item(item: ActionItem, labels: DocumentLabels) -> str:
    """Format a single action item as 'description (Owner: X)' or '(Owner: Unassigned)'."""
    owner = item.owner.strip() if item.owner else None
    if owner:
        return f"{item.description} ({labels['owner']}: {owner})"
    return f"{item.description} ({labels['owner']}: {labels['unassigned']})"


# ============================================
# Word Document Generation
# ============================================

def _set_rtl_paragraph(paragraph) -> None:
    """Set RTL direction for a Word paragraph."""
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement('w:bidi')
    bidi.set(qn('w:val'), '1')
    pPr.append(bidi)


def generate_word_document(analysis: AnalysisResult, language: str = "en") -> str:
    """
    Build a Word document from analysis with language-aware headings.

    Uses analysis.translated_transcript for the Transcript section so the Word
    output matches the selected output language. Supports RTL for Hebrew and Arabic.

    Args:
        analysis: Structured analysis (summary, participants, decisions,
            action_items, translated_transcript).
        language: Output language code (en, he, fr, es, ar). Default en.

    Returns:
        Absolute path to the generated .docx file. Caller is responsible for cleanup.

    Raises:
        OSError: If the temp file cannot be created or written.
    """
    labels = get_labels(language)
    rtl = is_rtl(language)
    doc = Document()

    # Set document language for RTL if needed
    if rtl:
        # Set default paragraph direction
        style = doc.styles['Normal']
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    # Title
    title = doc.add_heading(labels["title"], level=0)
    if rtl:
        title.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_rtl_paragraph(title)

    # Summary section
    heading = doc.add_heading(labels["summary"], level=1)
    if rtl:
        heading.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_rtl_paragraph(heading)
    
    summary_text = (analysis.summary or "").strip()
    para = doc.add_paragraph(summary_text if summary_text else f"({labels['none']})")
    if rtl:
        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_rtl_paragraph(para)

    # Transcript section
    heading = doc.add_heading(labels["transcript"], level=1)
    if rtl:
        heading.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_rtl_paragraph(heading)
    
    transcript_text = (analysis.translated_transcript or "").strip()
    para = doc.add_paragraph(transcript_text if transcript_text else f"({labels['none']})")
    if rtl:
        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_rtl_paragraph(para)

    # Participants section
    heading = doc.add_heading(labels["participants"], level=1)
    if rtl:
        heading.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_rtl_paragraph(heading)
    
    if not analysis.participants:
        para = doc.add_paragraph(labels["none"])
        if rtl:
            para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _set_rtl_paragraph(para)
    else:
        for p in analysis.participants:
            para = doc.add_paragraph(p, style="List Bullet")
            if rtl:
                para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                _set_rtl_paragraph(para)

    # Decisions section
    heading = doc.add_heading(labels["decisions"], level=1)
    if rtl:
        heading.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_rtl_paragraph(heading)
    
    if not analysis.decisions:
        para = doc.add_paragraph(labels["none"])
        if rtl:
            para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _set_rtl_paragraph(para)
    else:
        for d in analysis.decisions:
            para = doc.add_paragraph(d, style="List Bullet")
            if rtl:
                para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                _set_rtl_paragraph(para)

    # Action Items section
    heading = doc.add_heading(labels["actions"], level=1)
    if rtl:
        heading.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_rtl_paragraph(heading)
    
    if not analysis.action_items:
        para = doc.add_paragraph(labels["none"])
        if rtl:
            para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _set_rtl_paragraph(para)
    else:
        for item in analysis.action_items:
            para = doc.add_paragraph(_format_action_item(item, labels), style="List Bullet")
            if rtl:
                para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                _set_rtl_paragraph(para)

    # Footer
    doc.add_paragraph()  # Spacer
    footer = doc.add_paragraph(f"{labels['generated_by']} • {datetime.now().strftime('%Y-%m-%d')}")
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in footer.runs:
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(128, 128, 128)

    # Save to temp file
    fd, path = tempfile.mkstemp(suffix=".docx")
    try:
        os.close(fd)
        doc.save(path)
    except Exception:
        file_utils.delete_temp_file(path)
        raise
    return path


# ============================================
# PDF Document Generation
# ============================================

def _create_pdf_styles(rtl: bool = False) -> dict:
    """Create PDF paragraph styles with RTL support if needed."""
    styles = getSampleStyleSheet()
    alignment = TA_RIGHT if rtl else TA_LEFT
    
    # Title style
    styles.add(ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=20,
        alignment=TA_CENTER,
        textColor='#4F46E5',  # Indigo
    ))
    
    # Section heading style
    styles.add(ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=16,
        spaceAfter=8,
        alignment=alignment,
        textColor='#1F2937',
    ))
    
    # Body text style
    styles.add(ParagraphStyle(
        'BodyText',
        parent=styles['Normal'],
        fontSize=11,
        leading=16,
        alignment=alignment,
        textColor='#374151',
    ))
    
    # List item style
    styles.add(ParagraphStyle(
        'ListItem',
        parent=styles['Normal'],
        fontSize=11,
        leading=14,
        alignment=alignment,
        leftIndent=20,
        textColor='#374151',
    ))
    
    # Footer style
    styles.add(ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=9,
        alignment=TA_CENTER,
        textColor='#9CA3AF',
    ))
    
    return styles


def generate_pdf_document(analysis: AnalysisResult, language: str = "en") -> str:
    """
    Build a PDF document from analysis with language-aware headings.

    Uses analysis.translated_transcript for the Transcript section so the PDF
    output matches the selected output language. Supports RTL for Hebrew and Arabic.

    Args:
        analysis: Structured analysis (summary, participants, decisions,
            action_items, translated_transcript).
        language: Output language code (en, he, fr, es, ar). Default en.

    Returns:
        Absolute path to the generated .pdf file. Caller is responsible for cleanup.

    Raises:
        OSError: If the temp file cannot be created or written.
    """
    labels = get_labels(language)
    rtl = is_rtl(language)
    styles = _create_pdf_styles(rtl)
    
    # Create temp file
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    
    try:
        # Create PDF document
        doc = SimpleDocTemplate(
            path,
            pagesize=A4,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )
        
        story = []
        
        # Title
        story.append(Paragraph(labels["title"], styles['DocTitle']))
        story.append(Spacer(1, 12))
        
        # Summary section
        story.append(Paragraph(labels["summary"], styles['SectionHeading']))
        summary_text = (analysis.summary or "").strip() or f"({labels['none']})"
        # Handle special characters in text
        summary_text = summary_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        story.append(Paragraph(summary_text, styles['BodyText']))
        story.append(Spacer(1, 8))
        
        # Transcript section
        story.append(Paragraph(labels["transcript"], styles['SectionHeading']))
        transcript_text = (analysis.translated_transcript or "").strip() or f"({labels['none']})"
        # Escape HTML entities and handle newlines
        transcript_text = transcript_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        transcript_text = transcript_text.replace('\n', '<br/>')
        story.append(Paragraph(transcript_text, styles['BodyText']))
        story.append(Spacer(1, 8))
        
        # Participants section
        story.append(Paragraph(labels["participants"], styles['SectionHeading']))
        if not analysis.participants:
            story.append(Paragraph(labels["none"], styles['BodyText']))
        else:
            for p in analysis.participants:
                p_escaped = p.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                story.append(Paragraph(f"• {p_escaped}", styles['ListItem']))
        story.append(Spacer(1, 8))
        
        # Decisions section
        story.append(Paragraph(labels["decisions"], styles['SectionHeading']))
        if not analysis.decisions:
            story.append(Paragraph(labels["none"], styles['BodyText']))
        else:
            for d in analysis.decisions:
                d_escaped = d.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                story.append(Paragraph(f"• {d_escaped}", styles['ListItem']))
        story.append(Spacer(1, 8))
        
        # Action Items section
        story.append(Paragraph(labels["actions"], styles['SectionHeading']))
        if not analysis.action_items:
            story.append(Paragraph(labels["none"], styles['BodyText']))
        else:
            for item in analysis.action_items:
                item_text = _format_action_item(item, labels)
                item_escaped = item_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                story.append(Paragraph(f"• {item_escaped}", styles['ListItem']))
        
        # Footer
        story.append(Spacer(1, 24))
        footer_text = f"{labels['generated_by']} • {datetime.now().strftime('%Y-%m-%d')}"
        story.append(Paragraph(footer_text, styles['Footer']))
        
        # Build PDF
        doc.build(story)
        
    except Exception:
        file_utils.delete_temp_file(path)
        raise
    
    return path


# ============================================
# Legacy function (backward compatibility)
# ============================================

def generate_document(analysis: AnalysisResult, language: str = "en") -> str:
    """
    Build a Word document from analysis (backward-compatible wrapper).
    
    Delegates to generate_word_document.
    """
    return generate_word_document(analysis, language)
