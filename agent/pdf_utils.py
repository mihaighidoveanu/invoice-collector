"""Shared PDF text extraction utility."""

from pathlib import Path

import pdfplumber


def extract_text(pdf_path: Path) -> str:
    text_parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)
