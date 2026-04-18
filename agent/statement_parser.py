import json
import logging
from datetime import date
from pathlib import Path

import pdfplumber
from langchain_anthropic import ChatAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings
from models import AmbiguousNormalization, Transaction

logger = logging.getLogger(__name__)


def _build_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.llm_model_name,
        api_key=settings.anthropic_api_key,
    )


def _extract_text(pdf_path: Path) -> str:
    text_parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


_PARSE_PROMPT = """\
You are a financial data extractor. Given raw bank statement text, extract every transaction \
and return a JSON array. Each element must have:
  - "raw_description": the original text from the statement (string)
  - "vendor": a clean, normalized business name (e.g. "AMZN MKTP US*AB12" → "Amazon")
  - "amount": transaction amount as a positive float
  - "currency": ISO 4217 currency code (e.g. "RON", "EUR", "USD")
  - "date": date in YYYY-MM-DD format
  - "ambiguous": true if the vendor name normalization was uncertain, else false
  - "confidence_note": brief note when ambiguous is true, else ""

Only include transactions from {target_month} (YYYY-MM).
Return ONLY the JSON array, no prose.

Bank statement text:
{text}
"""


def _call_llm(text: str, target_month: str, llm: ChatAnthropic) -> str:
    prompt = _PARSE_PROMPT.format(target_month=target_month, text=text)
    response = llm.invoke(prompt)
    return str(response.content)


def _parse_llm_response(
    raw: str,
) -> tuple[list[Transaction], list[AmbiguousNormalization]]:
    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]

    data = json.loads(cleaned)

    transactions: list[Transaction] = []
    ambiguous: list[AmbiguousNormalization] = []

    for item in data:
        tx = Transaction(
            vendor=item["vendor"],
            amount=float(item["amount"]),
            currency=item["currency"],
            date=date.fromisoformat(item["date"]),
            raw_description=item["raw_description"],
        )
        transactions.append(tx)

        if item.get("ambiguous"):
            ambiguous.append(
                AmbiguousNormalization(
                    raw_description=item["raw_description"],
                    normalized_name=item["vendor"],
                    confidence_note=item.get("confidence_note", ""),
                )
            )

    return transactions, ambiguous


def _log_normalizations(transactions: list[Transaction], ambiguous_set: set[str]) -> None:
    logger.info("=== Vendor normalizations (%d transactions) ===", len(transactions))
    for tx in transactions:
        tag = "  [ambiguous]" if tx.raw_description in ambiguous_set else ""
        logger.info('  %-45s → "%s"%s', f'"{tx.raw_description}"', tx.vendor, tag)
    logger.info("=== End vendor normalizations ===")


def parse_statement(
    pdf_path: Path,
    target_month: str,
) -> tuple[list[Transaction], list[AmbiguousNormalization]]:
    """Parse bank statement PDF and return transactions for the target month.

    Args:
        pdf_path: Path to the bank statement PDF.
        target_month: Month filter in YYYY-MM format.

    Returns:
        Tuple of (transactions, ambiguous_normalizations).
    """
    text = _extract_text(pdf_path)
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
        return _call_llm(text, target_month, llm)

    try:
        raw = _call_with_retry()
    except Exception as exc:
        logger.error("LLM call failed after all retries: %s", exc)
        return [], []

    try:
        transactions, ambiguous = _parse_llm_response(raw)
    except Exception as exc:
        logger.error("Failed to parse LLM response: %s", exc)
        return [], []

    ambiguous_raw_set = {a.raw_description for a in ambiguous}
    _log_normalizations(transactions, ambiguous_raw_set)

    return transactions, ambiguous
