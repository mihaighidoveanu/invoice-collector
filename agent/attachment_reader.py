"""Phase 4 — Attachment reader.

pdfplumber-first gate: only calls the LLM when extracted text >= 50 chars.
Scanned/image PDFs fall through the gate and are returned as not-an-invoice.
"""

import json
import logging
from datetime import date
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.pdf_utils import extract_text as _extract_text
from config import settings
from models import AttachmentReading

logger = logging.getLogger(__name__)

_MIN_TEXT_LENGTH = 50

_INVOICE_PROMPT = """\
You are an accounting document detector. Given the text of a PDF, determine whether it is \
a financial supporting document for bookkeeping — this includes invoices (factura), receipts, \
payment orders (ordin de plata), salary payment statements (stat de plata salarii), or any \
official document that records a monetary transaction or obligation.

If it IS such a document, respond with JSON:
{{"is_invoice": true, "vendor": "<payer or payee name>", "amount": <float — the primary amount paid or owed>,
"date": "<YYYY-MM-DD>", "confidence": <0.0-1.0>}}

If it is NOT a financial document (e.g. attendance sheet / pontaj, cover letter, informational report), \
respond with JSON:
{{"is_invoice": false}}

Return ONLY the JSON object, no prose.

PDF text:
{text}
"""


def _build_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.llm_model_name,
        api_key=settings.anthropic_api_key,
    )


def _call_llm(text: str, llm: ChatAnthropic) -> str:
    prompt = _INVOICE_PROMPT.format(text=text)
    response = llm.invoke(prompt)
    return str(response.content)


def _parse_llm_response(raw: str) -> AttachmentReading:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]

    data = json.loads(cleaned)

    if not data.get("is_invoice", False):
        return AttachmentReading(is_invoice=False)

    invoice_date: date | None = None
    raw_date = data.get("date")
    if raw_date:
        try:
            invoice_date = date.fromisoformat(raw_date)
        except ValueError:
            logger.warning("Could not parse invoice date: %s", raw_date)

    return AttachmentReading(
        is_invoice=True,
        vendor=data.get("vendor"),
        amount=float(data["amount"]) if data.get("amount") is not None else None,
        invoice_date=invoice_date,
        confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
    )


def read_attachment(pdf_path: Path) -> AttachmentReading:
    """Analyse a PDF and return whether it is an invoice with extracted fields.

    Args:
        pdf_path: Local path to the downloaded PDF attachment.

    Returns:
        AttachmentReading — is_invoice=False for scanned/unreadable PDFs.
    """
    try:
        text = _extract_text(pdf_path)
    except Exception as exc:
        logger.error("pdfplumber failed on %s: %s", pdf_path, exc)
        return AttachmentReading(is_invoice=False)

    if len(text) < _MIN_TEXT_LENGTH:
        logger.info("PDF %s has insufficient text (%d chars), skipping LLM", pdf_path, len(text))
        return AttachmentReading(is_invoice=False)

    llm = _build_llm()

    @retry(
        stop=stop_after_attempt(settings.llm_max_retries),
        wait=wait_exponential(
            min=settings.llm_retry_wait_min,
            max=settings.llm_retry_wait_max,
        ),
        reraise=False,
    )
    def _call_with_retry() -> str:
        return _call_llm(text, llm)

    try:
        raw = _call_with_retry()
    except Exception as exc:
        logger.error("LLM call failed for %s: %s", pdf_path, exc)
        return AttachmentReading(is_invoice=False)

    try:
        return _parse_llm_response(raw)
    except Exception as exc:
        logger.error("Failed to parse LLM response for %s: %s", pdf_path, exc)
        return AttachmentReading(is_invoice=False)
