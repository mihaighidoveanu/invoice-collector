import json
import logging
from datetime import date
from pathlib import Path

import pdfplumber
from langchain_anthropic import ChatAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings
from models import Transaction

logger = logging.getLogger(__name__)


def _build_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.llm_model_name,
        api_key=settings.anthropic_api_key,
        max_tokens=settings.llm_max_tokens,
    )


def _extract_text(pdf_path: Path) -> str:
    text_parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)

# TODO: remove currency field (all transactions should be in RON)
_PARSE_PROMPT = """\
You are a financial data extractor. Given raw bank statement text, extract every outgoing transaction \
and return a JSON array. Skip bank comissions, bank taxes and the monthly bank package.
Each element must have:
  - "raw_description": the original text from the statement (string)
  - "vendor": a clean, normalized business name (e.g. "AMZN MKTP US*AB12" → "Amazon") or person name
  - "amount": transaction amount as a positive float
  - "date": date in YYYY-MM-DD format
Return ONLY the JSON array, no prose.


Bank statement text:
{text}
"""


def _call_llm(text: str, llm: ChatAnthropic) -> str:
    prompt = _PARSE_PROMPT.format(text=text)
    response = llm.invoke(prompt)
    return response.content


def _parse_llm_response(raw: str) -> list[Transaction]:
    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]

    data = json.loads(cleaned)

    return [
        Transaction(
            vendor=item["vendor"],
            amount=float(item["amount"]),
            date=date.fromisoformat(item["date"]),
            raw_description=item["raw_description"],
        )
        for item in data
    ]


def _log_normalizations(transactions: list[Transaction]) -> None:
    logger.info("=== Vendor normalizations (%d transactions) ===", len(transactions))
    for tx in transactions:
        logger.info('  %-45s → "%s"', f'"{tx.raw_description}"', tx.vendor)
    logger.info("=== End vendor normalizations ===")


def parse_statement(pdf_path: Path) -> list[Transaction]:
    """Parse bank statement PDF and return transactions."""
    text = _extract_text(pdf_path)
    llm = _build_llm()

    @retry(
        stop=stop_after_attempt(settings.llm_max_retries),
        wait=wait_exponential(
            min=settings.llm_retry_wait_min,
            max=settings.llm_retry_wait_max,
        ),
        reraise=True,
    )
    def _call_with_retry() -> str:
        return _call_llm(text, llm)

    try:
        raw = _call_with_retry()
    except Exception as exc:
        logger.error("LLM call failed after all retries: %s", exc)
        return []

    try:
        transactions = _parse_llm_response(raw)
    except Exception as exc:
        logger.error("Failed to parse LLM response: %s", exc)
        return []

    _log_normalizations(transactions)

    return transactions

if __name__ == '__main__':

    pdf_path = 'input/0_Extrase_RO73BTRLRONCRT0CR2266601_2026-01-01_2026-01-31_CALEIDOSCOP_PRIME_BUZZ_S_R_L.PDF'
    text = _extract_text(pdf_path)

    llm = _build_llm()
    response = _call_llm(text, llm)

    transactions = _parse_llm_response(response)
    for transaction in transactions:
        print(transaction, '\n')
    print("Count", len(transactions))
