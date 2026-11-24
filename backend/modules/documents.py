"""Automated Document Generator (DOCX, PDF, Markdown) for reports & LMS assignments."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Pt, RGBColor
from fpdf import FPDF

from backend.core.config import Settings


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    return cleaned.strip("_")[:60] or "dokumen"


class DocumentService:
    """Creates structured DOCX, PDF, and Markdown files stored in outputs/documents/."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_document(
        self,
        title: str,
        sections: list[dict[str, Any]],
        fmt: str = "docx",
        author: str = "Boss",
        subtitle: str = "",
    ) -> dict[str, Any]:
        """Generate a clean document in 'docx', 'pdf', or 'md' format."""
        fmt_clean = fmt.strip().lower()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{_slugify(title)}_{stamp}"

        if fmt_clean == "docx":
            path = self._build_docx(base_name, title, subtitle, author, sections)
        elif fmt_clean == "pdf":
            path = self._build_pdf(base_name, title, subtitle, author, sections)
        elif fmt_clean in ("md", "markdown"):
            path = self._build_markdown(base_name, title, subtitle, author, sections)
        else:
            raise ValueError("Format dokumen harus 'docx', 'pdf', atau 'md'.")

        return {
            "filename": path.name,
            "path": str(path),
            "format": fmt_clean,
            "size_bytes": path.stat().st_size,
            "download_url": f"/api/documents/download/{path.name}",
        }

    def list_documents(self) -> list[dict[str, Any]]:
        """List all generated documents sorted newest first."""
        files = sorted(
            self.settings.documents_dir.glob("*.*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [
            {
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "modified_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "download_url": f"/api/documents/download/{f.name}",
            }
            for f in files[:30]
        ]

    def resolve_document_path(self, filename: str) -> Path:
        safe_name = Path(filename).name
        target = self.settings.documents_dir / safe_name
        if not target.exists():
            raise FileNotFoundError(f"Dokumen tidak ditemukan: {safe_name}")
        return target

    def _build_docx(
        self,
        base_name: str,
        title: str,
        subtitle: str,
        author: str,
        sections: list[dict[str, Any]],
    ) -> Path:
        doc = Document()
        normal_style = doc.styles["Normal"]
        normal_style.font.name = "Calibri"
        normal_style.font.size = Pt(11)

        heading = doc.add_heading(title, level=0)
        if heading.runs:
            heading.runs[0].font.color.rgb = RGBColor(0x1E, 0x29, 0x3B)

        meta_text = f"Disusun oleh: {author}  |  Tanggal: {datetime.now().strftime('%d %B %Y')}"
        if subtitle:
            meta_text = f"{subtitle}\n{meta_text}"
        meta_para = doc.add_paragraph(meta_text)
        if meta_para.runs:
            meta_para.runs[0].font.size = Pt(9.5)
            meta_para.runs[0].font.color.rgb = RGBColor(0x64, 0x74, 0x8B)

        for section in sections:
            sec_heading = str(section.get("heading", "")).strip()
            if sec_heading:
                doc.add_heading(sec_heading, level=1)

            content = str(section.get("content", "")).strip()
            if content:
                for paragraph in content.split("\n\n"):
                    doc.add_paragraph(paragraph.strip())

            bullets = section.get("bullets") or []
            for bullet in bullets:
                doc.add_paragraph(str(bullet), style="List Bullet")

        out_path = self.settings.documents_dir / f"{base_name}.docx"
        doc.save(str(out_path))
        return out_path

    def _build_pdf(
        self,
        base_name: str,
        title: str,
        subtitle: str,
        author: str,
        sections: list[dict[str, Any]],
    ) -> Path:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=18)
        pdf.add_page()

        # Sanitize to latin-1 safe text for core Helvetica font
        def clean(text: str) -> str:
            return text.encode("latin-1", errors="replace").decode("latin-1")

        pdf.set_font("Helvetica", "B", 18)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 10, clean(title))
        pdf.ln(1)

        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(100, 116, 139)
        meta = f"{subtitle} | " if subtitle else ""
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 6, clean(f"{meta}Author: {author} | {datetime.now().strftime('%Y-%m-%d')}"))
        pdf.ln(4)
        pdf.set_text_color(15, 23, 42)

        for section in sections:
            sec_heading = str(section.get("heading", "")).strip()
            if sec_heading:
                pdf.set_font("Helvetica", "B", 13)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(0, 8, clean(sec_heading))
                pdf.ln(1)

            content = str(section.get("content", "")).strip()
            if content:
                pdf.set_font("Helvetica", "", 11)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(0, 6.5, clean(content))
                pdf.ln(2)

            bullets = section.get("bullets") or []
            if bullets:
                pdf.set_font("Helvetica", "", 11)
                for item in bullets:
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(0, 6.5, clean(f"  - {item}"))
                pdf.ln(2)

        out_path = self.settings.documents_dir / f"{base_name}.pdf"
        pdf.output(str(out_path))
        return out_path

    def _build_markdown(
        self,
        base_name: str,
        title: str,
        subtitle: str,
        author: str,
        sections: list[dict[str, Any]],
    ) -> Path:
        lines = [f"# {title}"]
        if subtitle:
            lines.append(f"*{subtitle}*")
        lines.append(f"\n> Disusun oleh: **{author}** | Tanggal: {datetime.now().strftime('%Y-%m-%d')}\n")

        for section in sections:
            if section.get("heading"):
                lines.append(f"## {section['heading']}\n")
            if section.get("content"):
                lines.append(f"{section['content']}\n")
            for bullet in section.get("bullets") or []:
                lines.append(f"- {bullet}")
            lines.append("")

        out_path = self.settings.documents_dir / f"{base_name}.md"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return out_path
