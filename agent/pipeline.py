"""Phase 5 — Pipeline orchestrator.

Ties together statement parsing, rule building, Gmail search,
attachment downloading, and invoice-to-transaction matching.
"""

import calendar
import logging
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from agent.attachment_reader import read_attachment
from agent.gmail_tools import build_gmail_query, download_attachment, list_emails_with_attachments
from agent.pdf_utils import extract_text
from agent.rule_builder import build_vendor_rules
from agent.run_artifacts import RunArtifacts
from agent.statement_parser import parse_statement
from config import settings
from models import (
    AttachmentReading,
    FailureReason,
    InvoiceResult,
    Transaction,
    VendorRule,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Target month / analysis window
# ---------------------------------------------------------------------------


def _derive_target_month(transactions: list[Transaction]) -> str:
    """Return YYYY-MM for the most common month among transaction dates."""
    counts: dict[str, int] = defaultdict(int)
    for tx in transactions:
        counts[tx.date.strftime("%Y-%m")] += 1
    return max(counts, key=lambda k: counts[k])

def _analysis_window(target_month: str) -> tuple[date, date]:
    """Return (period_start, period_end) spanning the target month through +5 days.

    E.g. "2025-03" → (2025-03-01, 2025-04-05).
    """
    year, month = int(target_month[:4]), int(target_month[5:7])

    period_start = date(year, month, 1)

    _, last_day = calendar.monthrange(year, month)
    period_end = date(year, month, last_day) + timedelta(days=6)  # exclusive, covers through +5 days
    return period_start, period_end


# ---------------------------------------------------------------------------
# Amount helpers
# ---------------------------------------------------------------------------


def _amount_strings(amount: float) -> list[str]:
    """Return all plausible string encodings for an amount (EU/US formats)."""
    total_cents = round(amount * 100)
    int_part = total_cents // 100
    dec_part = total_cents % 100

    strs = [
        f"{int_part}.{dec_part:02d}",   # 1500.00
        f"{int_part},{dec_part:02d}",   # 1500,00
    ]
    if int_part >= 1000:
        int_str_eu = f"{int_part:,}".replace(",", ".")
        strs.append(f"{int_str_eu},{dec_part:02d}")  # 1.500,00
        int_str_us = f"{int_part:,}"
        strs.append(f"{int_str_us}.{dec_part:02d}")  # 1,500.00

    return list(dict.fromkeys(strs))


def _build_amount_lookup(txs: list[Transaction]) -> dict[str, list[int]]:
    """Map every plausible amount string encoding to the indices of matching transactions."""
    lookup: defaultdict[str, list[int]] = defaultdict(list)
    for idx, tx in enumerate(txs):
        for s in _amount_strings(tx.amount):
            lookup[s].append(idx)
    return dict(lookup)


def _build_amount_regex(amount_strs: Iterable[str]) -> re.Pattern:
    # Sort longest first so more-specific patterns win over substrings.
    escaped = sorted([re.escape(s) for s in amount_strs], key=len, reverse=True)
    return re.compile("|".join(escaped))


# ---------------------------------------------------------------------------
# Vendor matching
# ---------------------------------------------------------------------------


def _vendor_match(tx_vendor: str, candidate: str) -> bool:
    tx = tx_vendor.lower()
    cv = candidate.lower()
    return tx in cv or cv in tx


# ---------------------------------------------------------------------------
# Transaction assignment
# ---------------------------------------------------------------------------


def _assign_to_transaction(
    reading: AttachmentReading,
    hits: list[str],
    candidate_vendor: str | None,
    transactions: list[Transaction],
    claimed: set[int],
    amount_lookup: dict[str, list[int]],
) -> int | None:
    """Try to assign a confirmed invoice to an unclaimed transaction.

    Returns the matched transaction index, or None if ambiguous/no match.
    """
    matching: set[int] = set()
    for hit in hits:
        for idx in amount_lookup.get(hit, []):
            if idx not in claimed:
                matching.add(idx)

    if not matching:
        return None

    # Sender-keyword vendor tiebreak (highest priority)
    if candidate_vendor:
        vendor_hits = [i for i in matching if _vendor_match(transactions[i].vendor, candidate_vendor)]
        if len(vendor_hits) == 1:
            return vendor_hits[0]

    # LLM-extracted vendor tiebreak
    if reading.vendor:
        vendor_hits = [i for i in matching if _vendor_match(transactions[i].vendor, reading.vendor)]
        if len(vendor_hits) == 1:
            return vendor_hits[0]

    # Amount-only: claim only when unambiguous
    if len(matching) == 1:
        return next(iter(matching))

    return None


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    bank_statement_path: Path,
    target_month: str | None = None,
    run_dir: Path | None = None,
) -> tuple[list[InvoiceResult], str]:
    """Run the full invoice collection pipeline.

    Args:
        bank_statement_path: Path to the bank statement PDF.
        target_month: Override the derived target month (YYYY-MM). If None,
            it is inferred from the most common transaction month.
        run_dir: Directory to persist intermediate stage outputs. If None,
            no intermediate artifacts are written.

    Returns:
        Tuple of (invoice_results, target_month_str).
    """
    artifacts = RunArtifacts(run_dir, str(bank_statement_path)) if run_dir else None

    # --- Phase 1: parse statement ---
    transactions = parse_statement(bank_statement_path)
    if artifacts:
        artifacts.save("01_transactions.json", transactions)

    if not transactions:
        logger.warning("No transactions parsed; returning empty results.")
        return [], target_month or ""

    derived_month = target_month or _derive_target_month(transactions)
    if artifacts:
        artifacts.save_meta(derived_month)

    period_start, period_end = _analysis_window(derived_month)
    logger.info(
        "Target month: %s | Analysis window: %s → %s",
        derived_month,
        period_start,
        period_end,
    )

    # --- Phase 2: build vendor rules ---
    vendor_rules = build_vendor_rules(transactions)
    if artifacts:
        artifacts.save("02_rules.json", vendor_rules)

    # --- Phase 3: fetch emails (server-side pre-filter) ---
    query = build_gmail_query(vendor_rules, period_start, period_end)
    emails = list_emails_with_attachments(query)
    if artifacts:
        artifacts.save("03_emails.json", emails)
    logger.info("Processing %d emails against %d transactions", len(emails), len(transactions))

    # --- Phase 4: amount lookup and sender→vendor mapping ---
    amount_lookup = _build_amount_lookup(transactions)
    amount_regex = _build_amount_regex(amount_lookup.keys())
    sender_to_vendor = {kw: r.vendor for r in vendor_rules for kw in r.sender_keywords}

    attachments_dir = (run_dir / "attachments") if run_dir else (settings.invoice_output_dir / "attachments")

    claimed: set[int] = set()
    found_results: dict[int, InvoiceResult] = {}
    readings_log: list[dict] = []

    # --- Phase 5: iterate emails and attachments ---
    for email in emails:
        if len(claimed) == len(transactions):
            logger.info("All transactions matched; stopping email scan early.")
            break

        sender_lower = email.sender.lower()
        candidate_vendor = next(
            (v for kw, v in sender_to_vendor.items() if kw in sender_lower), None
        )

        for filename in email.attachment_filenames:
            if not filename.lower().endswith(".pdf"):
                continue

            try:
                local_path = download_attachment(email.email_id, filename, attachments_dir)
            except Exception as exc:
                logger.warning("Failed to download %s from %s: %s", filename, email.email_id, exc)
                continue

            try:
                text = extract_text(local_path)
            except Exception as exc:
                logger.warning("Failed to extract text from %s: %s", local_path, exc)
                continue

            hits = amount_regex.findall(text)
            if not hits:
                logger.debug("No amount match in %s; skipping LLM", filename)
                continue

            try:
                reading = read_attachment(local_path)
            except Exception as exc:
                logger.warning("LLM read failed for %s: %s", local_path, exc)
                continue

            readings_log.append({
                "email_id": email.email_id,
                "filename": filename,
                "reading": reading.model_dump(mode="json"),
            })

            if not reading.is_invoice:
                continue

            tx_idx = _assign_to_transaction(
                reading, hits, candidate_vendor, transactions, claimed, amount_lookup
            )
            if tx_idx is not None:
                claimed.add(tx_idx)
                found_results[tx_idx] = InvoiceResult(
                    transaction=transactions[tx_idx],
                    email_id=email.email_id,
                    attachment_path=local_path,
                    status="found",
                )

    if artifacts:
        artifacts.save("04_readings.json", readings_log)

    # --- Phase 6: assemble final results ---
    results: list[InvoiceResult] = []
    for idx, tx in enumerate(transactions):
        if idx in found_results:
            results.append(found_results[idx])
        else:
            results.append(InvoiceResult(
                transaction=tx,
                status="missing",
                failure_reason=FailureReason.AMOUNT_MISMATCH,
            ))

    if artifacts:
        artifacts.save("05_results.json", results)

    return results, derived_month
