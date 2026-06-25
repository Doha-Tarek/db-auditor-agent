# reports/pdf_generator.py
# Converts rendered HTML to PDF using WeasyPrint.
# Called by reporter.py after HTML is generated.

import os
from pathlib import Path
from datetime import datetime
from tools.audit_logger import logger


# ─────────────────────────────────────────────
# OUTPUT FOLDER
# ─────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# GENERATE PDF
# ─────────────────────────────────────────────

def generate_pdf(html_content: str, filename: str) -> str:
    """
    Converts HTML string to PDF file using WeasyPrint.
    Saves to reports/output/ folder.

    Args:
        html_content: rendered HTML string
        filename:     output filename without extension

    Returns:
        Full path to the generated PDF file
    """
    try:
        from weasyprint import HTML, CSS

        output_path = OUTPUT_DIR / f"{filename}.pdf"

        # generate PDF from HTML string
        HTML(string=html_content).write_pdf(
            target=str(output_path),
            stylesheets=[
                CSS(string="""
                    @page {
                        size: A4;
                        margin: 15mm 12mm;
                    }
                    body {
                        font-size: 12px;
                    }
                """)
            ]
        )

        logger.info(f"pdf_generator | PDF created | {output_path}")
        return str(output_path)

    except Exception as e:
        logger.error(f"pdf_generator | PDF generation failed | {e}")
        raise


# ─────────────────────────────────────────────
# SAVE HTML
# ─────────────────────────────────────────────

def save_html(html_content: str, filename: str) -> str:
    """
    Saves rendered HTML string to reports/output/ folder.

    Args:
        html_content: rendered HTML string
        filename:     output filename without extension

    Returns:
        Full path to the saved HTML file
    """
    try:
        output_path = OUTPUT_DIR / f"{filename}.html"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info(f"pdf_generator | HTML saved | {output_path}")
        return str(output_path)

    except Exception as e:
        logger.error(f"pdf_generator | HTML save failed | {e}")
        raise


# ─────────────────────────────────────────────
# BUILD FILENAME
# ─────────────────────────────────────────────

def build_filename(scan_id: str, report_type: str = "full") -> str:
    """
    Builds a timestamped filename for the report.

    Args:
        scan_id:     scan run UUID
        report_type: full | executive

    Returns:
        filename string without extension
        e.g. report_full_2026-06-10_abc12345
    """
    date_str  = datetime.now().strftime("%Y-%m-%d")
    short_id  = scan_id[:8]
    return f"report_{report_type}_{date_str}_{short_id}"