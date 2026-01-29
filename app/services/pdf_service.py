"""
PDF export service (WeasyPrint: HTML → PDF).

Produces PDFs from meeting analysis with correct rendering for Hebrew, Arabic,
English, French, and Spanish. Uses HTML + CSS so fonts and RTL are handled
properly; fonts are embedded in the PDF.

Architectural choice: WeasyPrint (HTML → PDF) instead of canvas-based generation
(reportlab) to fix Hebrew/Arabic rendering (squares) and font embedding issues.
"""

import html
import os
import tempfile
from datetime import datetime
from pathlib import Path

from app.models.schemas import ActionItem, AnalysisResult
from app.utils import file_utils
from app.utils.document_labels import get_labels, is_rtl, DocumentLabels


# Assets directory for fonts (local files, not CDN)
_BASE_DIR = Path(__file__).resolve().parent.parent
_FONTS_DIR = _BASE_DIR / "assets" / "fonts"

# Font files to try (family, filename). Place these in app/assets/fonts/ for full support.
_FONT_FILES = [
    ("Heebo", "Heebo-Regular.woff2"),           # Hebrew
    ("Heebo", "Heebo-Regular.woff"),
    ("Noto Sans Arabic", "NotoSansArabic-Regular.woff2"),
    ("Noto Sans Arabic", "NotoSansArabic-Regular.woff"),
    ("Noto Sans", "NotoSans-Regular.woff2"),   # Latin fallback
    ("Noto Sans", "NotoSans-Regular.woff"),
]


def _font_css() -> str:
    """Build @font-face rules for fonts that exist under assets/fonts. Embedded in PDF."""
    if not _FONTS_DIR.is_dir():
        return ""
    rules = []
    for family, filename in _FONT_FILES:
        path = _FONTS_DIR / filename
        if path.is_file():
            uri = path.as_uri()
            rules.append(
                f"@font-face {{ font-family: '{family}'; src: url('{uri}'); font-display: swap; }}"
            )
    return "\n".join(rules) if rules else ""


def _format_action_item(item: ActionItem, labels: DocumentLabels) -> str:
    """Format a single action item for display."""
    owner = item.owner.strip() if item.owner else None
    if owner:
        return f"{item.description} ({labels['owner']}: {owner})"
    return f"{item.description} ({labels['owner']}: {labels['unassigned']})"


def _escape(s: str) -> str:
    """Escape for HTML text content."""
    return html.escape(s, quote=True)


def _build_html_document(analysis: AnalysisResult, language: str) -> str:
    """
    Build semantic HTML for the meeting summary.
    Uses language-aware headings from document_labels. RTL for he/ar.
    """
    labels = get_labels(language)
    rtl = is_rtl(language)
    dir_attr = "rtl" if rtl else "ltr"
    direction_css = "direction: rtl; text-align: right;" if rtl else "direction: ltr; text-align: left;"

    font_css = _font_css()
    font_stack = "Heebo, 'Noto Sans Arabic', 'Noto Sans', sans-serif" if font_css else "sans-serif"

    title_esc = _escape(labels["title"])
    summary_heading = _escape(labels["summary"])
    transcript_heading = _escape(labels["transcript"])
    participants_heading = _escape(labels["participants"])
    decisions_heading = _escape(labels["decisions"])
    actions_heading = _escape(labels["actions"])
    none_esc = _escape(labels["none"])
    generated_esc = _escape(labels["generated_by"])
    date_str = datetime.now().strftime("%Y-%m-%d")

    summary_text = (analysis.summary or "").strip() or none_esc
    summary_esc = _escape(summary_text)

    transcript_text = (analysis.translated_transcript or "").strip() or none_esc
    transcript_esc = _escape(transcript_text).replace("\n", "<br>")

    # Participants list
    if analysis.participants:
        participants_items = "".join(
            f"<li>{_escape(p)}</li>" for p in analysis.participants
        )
        participants_body = f"<ul>{participants_items}</ul>"
    else:
        participants_body = f"<p>{none_esc}</p>"

    # Decisions list
    if analysis.decisions:
        decisions_items = "".join(
            f"<li>{_escape(d)}</li>" for d in analysis.decisions
        )
        decisions_body = f"<ul>{decisions_items}</ul>"
    else:
        decisions_body = f"<p>{none_esc}</p>"

    # Action items list
    if analysis.action_items:
        action_items_li = "".join(
            f"<li>{_escape(_format_action_item(item, labels))}</li>"
            for item in analysis.action_items
        )
        actions_body = f"<ul>{action_items_li}</ul>"
    else:
        actions_body = f"<p>{none_esc}</p>"

    html_content = f"""<!DOCTYPE html>
<html lang="{language}" dir="{dir_attr}">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title_esc}</title>
<style>
{font_css}
:root {{
  --font: {font_stack};
  --text: #1a1a1a;
  --muted: #4a4a4a;
  --border: #e5e5e5;
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: var(--font);
  font-size: 11pt;
  line-height: 1.6;
  color: var(--text);
  max-width: 210mm;
  margin: 0 auto;
  padding: 20mm;
  {direction_css}
}}
h1 {{
  font-size: 24pt;
  font-weight: 600;
  margin: 0 0 1.5em 0;
  border-bottom: 2px solid var(--border);
  padding-bottom: 0.5em;
}}
h2 {{
  font-size: 14pt;
  font-weight: 600;
  margin: 1.5em 0 0.5em 0;
  color: var(--text);
}}
p {{
  margin: 0 0 0.75em 0;
}}
ul {{
  margin: 0 0 0.75em 0;
  padding: 0 0 0 1.5em;
}}
li {{
  margin-bottom: 0.35em;
}}
section {{
  margin-bottom: 1.5em;
}}
section + section {{
  border-top: 1px solid var(--border);
  padding-top: 1em;
}}
footer {{
  margin-top: 2em;
  padding-top: 1em;
  border-top: 1px solid var(--border);
  font-size: 9pt;
  color: var(--muted);
  text-align: center;
}}
</style>
</head>
<body>
<main>
<h1>{title_esc}</h1>
<section>
<h2>{summary_heading}</h2>
<p>{summary_esc}</p>
</section>
<section>
<h2>{transcript_heading}</h2>
<p>{transcript_esc}</p>
</section>
<section>
<h2>{participants_heading}</h2>
{participants_body}
</section>
<section>
<h2>{decisions_heading}</h2>
{decisions_body}
</section>
<section>
<h2>{actions_heading}</h2>
{actions_body}
</section>
</main>
<footer>{generated_esc} · {date_str}</footer>
</body>
</html>
"""
    return html_content


def _ensure_weasyprint():
    """
    Import WeasyPrint and its font config. Lazy so the app can start without
    Pango/GObject installed (e.g. on Windows). Raises RuntimeError with
    setup instructions if native libs are missing.
    """
    try:
        from weasyprint import HTML as WeasyHTML
        from weasyprint.text.fonts import FontConfiguration
        return WeasyHTML, FontConfiguration
    except OSError as e:
        msg = str(e).lower()
        if "libgobject" in msg or "libpango" in msg or "cannot load library" in msg:
            raise RuntimeError(
                "PDF export requires WeasyPrint's native libraries (Pango/GObject). "
                "On Windows: install MSYS2, run 'pacman -S mingw-w64-x86_64-pango', "
                "then set WEASYPRINT_DLL_DIRECTORIES to the folder containing the DLLs "
                "(e.g. C:\\msys64\\mingw64\\bin). See: "
                "https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows"
            ) from e
        raise RuntimeError(f"WeasyPrint failed to load: {e}") from e


def generate_pdf_document(analysis: AnalysisResult, language: str = "en") -> str:
    """
    Generate a PDF from meeting analysis using WeasyPrint (HTML → PDF).

    Hebrew, Arabic, English, French, and Spanish render correctly with
    proper fonts and RTL where applicable. Fonts are embedded when available
    under app/assets/fonts/.

    Args:
        analysis: Structured analysis (summary, participants, decisions,
            action_items, translated_transcript).
        language: Output language code (en, he, fr, es, ar). Default en.

    Returns:
        Absolute path to the generated .pdf file. Caller is responsible for cleanup.

    Raises:
        RuntimeError: If WeasyPrint's native libs (Pango/GObject) are not available.
        OSError: If the temp file cannot be created or written.
    """
    WeasyHTML, FontConfiguration = _ensure_weasyprint()

    html_str = _build_html_document(analysis, language)
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    try:
        font_config = FontConfiguration()
        html_doc = WeasyHTML(string=html_str)
        html_doc.write_pdf(
            path,
            font_config=font_config,
        )
    except Exception:
        file_utils.delete_temp_file(path)
        raise

    return path
