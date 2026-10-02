"""Offline ReportLab CJK resume rendering. No browser or HTML execution."""
from __future__ import annotations

import html
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from .candidate import PROJECT_ROOT


def _in_private(path: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(PROJECT_ROOT / "private"):
        raise ValueError("PDF及预览包含个人信息，必须保留在本项目private目录")
    return path


def _generate(blocks: list[dict], output: Path) -> dict:
    # Keep optional PDF packages out of module imports, so basic CLI remains usable.
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    font_name = "STSong-Light"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    typography = str.maketrans({"—": "-", "–": "-", "‑": "-", "−": "-"})
    def text(value: str) -> str:
        return html.escape(str(value).translate(typography), quote=True).replace("\n", "<br/>")
    def footer(canvas, document):
        canvas.setFont(font_name, 7)
        canvas.setFillColor(colors.HexColor("#778792"))
        canvas.drawRightString(A4[0] - 36, 23, str(document.page))
    page_count = 0
    chosen = None
    for size in (9.8, 9.4, 9.0, 8.6):
        styles = {
            "title": ParagraphStyle("title", fontName=font_name, fontSize=18, leading=23, spaceAfter=5, textColor=colors.HexColor("#18384b"), wordWrap="CJK"),
            "heading": ParagraphStyle("heading", fontName=font_name, fontSize=size + 1.3, leading=size + 4.0, spaceBefore=9, spaceAfter=3, textColor=colors.HexColor("#18384b"), wordWrap="CJK", keepWithNext=True),
            "bullet": ParagraphStyle("bullet", fontName=font_name, fontSize=size, leading=size + 3.2, spaceAfter=3, leftIndent=9, firstLineIndent=-9, alignment=TA_LEFT, wordWrap="CJK"),
            "contact": ParagraphStyle("contact", fontName=font_name, fontSize=8, leading=10.5, spaceAfter=2, textColor=colors.HexColor("#425968"), wordWrap="CJK"),
            "target": ParagraphStyle("target", fontName=font_name, fontSize=9, leading=12, spaceAfter=3, textColor=colors.HexColor("#425968"), wordWrap="CJK"),
        }
        story = []
        for block in blocks:
            kind = block.get("kind", "contact")
            style = styles.get(kind, styles["contact"])
            rendered = text(block["text"])
            if kind == "bullet":
                rendered = "- " + rendered
            story.append(Paragraph(rendered, style))
        story.append(Spacer(1, 2))
        document = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=36, leftMargin=36,
                                     topMargin=31, bottomMargin=34, title="岗位版简历",
                                     author="career-ops reviewed facts", subject="人工审阅投递材料")
        document.build(story, onFirstPage=footer, onLaterPages=footer)
        page_count = document.page
        chosen = size
        if page_count == 1:
            break
    if not output.read_bytes().startswith(b"%PDF-"):
        raise RuntimeError("PDF输出格式无效")
    if page_count > 1:
        raise RuntimeError("已批准事实无法在可读字号内排入一页；请审阅后减少事实，不自动截断")
    return {"page_count": page_count, "font": font_name, "body_font_size": chosen,
            "renderer": "reportlab-offline-cjk", "text_verified": False, "visual_review": "pending"}


def write_resume_pdf(blocks: list[dict], output_path: str | Path) -> dict:
    output = _in_private(Path(output_path))
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROJECT_ROOT / "private" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    if importlib.util.find_spec("reportlab") is not None:
        return _generate(blocks, output)
    configured = os.environ.get("CAREER_OPS_PDF_PYTHON")
    if not configured:
        raise RuntimeError("当前Python缺少reportlab；请安装reportlab，或配置CAREER_OPS_PDF_PYTHON指向已安装依赖的Python")
    fallback = Path(configured)
    if not fallback.is_file():
        raise RuntimeError("CAREER_OPS_PDF_PYTHON没有指向可读的Python程序")
    data_path = tmp / ("pdf-input-" + uuid.uuid4().hex + ".json")
    data_path.write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    environment = dict(os.environ)
    environment.update({"TEMP": str(tmp), "TMP": str(tmp), "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTHONPATH": str(PROJECT_ROOT) + os.pathsep + environment.get("PYTHONPATH", "")})
    try:
        result = subprocess.run([str(fallback), "-m", "career_ops.pdf", str(data_path), str(output)],
                                cwd=str(PROJECT_ROOT), env=environment, capture_output=True,
                                text=True, timeout=60, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("bundle PDF renderer失败：" + result.stderr[-1200:])
        return json.loads(result.stdout)
    finally:
        data_path.unlink(missing_ok=True)


def inspect_pdf(path: str | Path) -> dict:
    path = _in_private(Path(path))
    if importlib.util.find_spec("pypdf"):
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        texts = [p.extract_text() for p in reader.pages]
    elif importlib.util.find_spec("fitz"):
        import fitz
        with fitz.open(str(path)) as document:
            texts = [page.get_text() for page in document]
    else:
        raise RuntimeError("PDF文本验收需要pypdf或PyMuPDF；当前环境都未找到")
    return {"page_count": len(texts), "text": "\n".join(texts), "page_texts": texts}


def render_pdf_preview(path: str | Path, output_dir: str | Path | None = None) -> list[str]:
    path = _in_private(Path(path))
    output = _in_private(Path(output_dir)) if output_dir else path.parent / "preview"
    output.mkdir(parents=True, exist_ok=True)
    if not importlib.util.find_spec("fitz"):
        raise RuntimeError("本环境无PyMuPDF预览器；请用系统Poppler或本地PDF阅读器视觉验收")
    import fitz
    paths = []
    with fitz.open(str(path)) as document:
        for number, page in enumerate(document, 1):
            png = output / f"page-{number}.png"
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(str(png))
            paths.append(str(png))
    return paths


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m career_ops.pdf blocks.json resume.pdf")
    source = _in_private(Path(sys.argv[1]))
    target = _in_private(Path(sys.argv[2]))
    print(json.dumps(_generate(json.loads(source.read_text(encoding="utf-8")), target), ensure_ascii=True))
