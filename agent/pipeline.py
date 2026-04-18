"""Phase 5 — Pipeline orchestrator.

Ties together statement parsing, rule building, Gmail search,
attachment downloading, and invoice-to-transaction matching.
"""

import logging
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from agent.attachment_reader import read_attachment
from agent.gmail_tools import download_attachment, list_emails_with_attachments
from agent.rule_builder import build_rules
from agent.statement_parser import parse_statement
from models import (
    AmbiguousNormalization,
    AttachmentReading,
    EmailMatch,
    FailureReason,
    InvoiceResult,
    SearchRule,
    Transaction,
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
    """Return (period_start, period_end) spanning the target month + the following month.

    E.g. "2025-03" → (2025-03-01, 2025-04-30).
    The end date is the last day of the month following the target month.
    """
    year, month = int(target_month[:4]), int(target_month[5:7])

    period_start = date(year, month, 1)

    # Advance two months to get the month after next, then subtract one day
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    after_next_month = next_month + 1
    after_next_year = next_year
    if after_next_month > 12:
        after_next_month = 1
        after_next_year += 1

    period_end = date(after_next_year, after_next_month, 1)
    # period_end is exclusive in the Gmail query, so passing the 1st of the month
    # after the analysis window end covers through the last day of the following month.
    return period_start, period_end


# ---------------------------------------------------------------------------
# Metadata matching
# ---------------------------------------------------------------------------


def _email_matches_rule(email: EmailMatch, rule: SearchRule) -> bool:
    """Return True if the email metadata matches the rule."""
    subject_lower = email.subject.lower()
    if any(kw in subject_lower for kw in rule.subject_keywords):
        return True

    filenames_lower = [fn.lower() for fn in email.attachment_filenames]
    for kw in rule.attachment_filename_keywords:
        if any(kw in fn for fn in filenames_lower):
            return True

    return False


def _find_matching_rule(email: EmailMatch, rules: list[SearchRule]) -> SearchRule | None:
    for rule in rules:
        if _email_matches_rule(email, rule):
            return rule
    return None


# ---------------------------------------------------------------------------
# Amount / vendor matching
# ---------------------------------------------------------------------------


def _vendor_match(tx_vendor: str, reading_vendor: str | None) -> bool:
    if not reading_vendor:
        return False
    tx = tx_vendor.lower()
    rv = reading_vendor.lower()
    return tx in rv or rv in tx


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------


def run_pipeline(
    bank_statement_path: Path,
    target_month: str | None = None,
) -> tuple[list[InvoiceResult], list[AmbiguousNormalization], str]:
    """Run the full invoice collection pipeline.

    Args:
        bank_statement_path: Path to the bank statement PDF.
        target_month: Override the derived target month (YYYY-MM). If None,
            it is inferred from the most common transaction month.

    Returns:
        Tuple of (invoice_results, ambiguous_normalizations, target_month_str).
    """
    # --- Phase 1: parse statement ---
    transactions, ambiguous = parse_statement(
        bank_statement_path,
        target_month or "",
    )

    if not transactions:
        logger.warning("No transactions parsed; returning empty results.")
        return [], ambiguous, target_month or ""

    derived_month = target_month or _derive_target_month(transactions)
    period_start, period_end = _analysis_window(derived_month)
    logger.info(
        "Target month: %s | Analysis window: %s → %s",
        derived_month,
        period_start,
        period_end,
    )

    # --- Phase 2: build rules ---
    rules = build_rules(transactions)

    # --- Phase 3: fetch emails ---
    emails = list_emails_with_attachments(period_start, period_end)
    logger.info("Processing %d emails against %d transactions", len(emails), len(transactions))

    # Pool of confirmed invoices: mapping from (email_id, filename) → (reading, email, local_path)
    # Keyed to prevent double-claiming the same attachment.
    invoice_pool: dict[tuple[str, str], tuple[AttachmentReading, EmailMatch, Path]] = {}

    # Transactions directly matched by metadata rule: tx_vendor → (email_id, filename)
    direct_matches: dict[str, tuple[str, str]] = {}

    # Precompute per-amount counts for early-exit check (B2)
    tx_amount_counts: Counter[float] = Counter(tx.amount for tx in transactions)

    for email in emails:
        if not email.attachment_filenames:
            continue

        filename = email.attachment_filenames[0]
        pool_key = (email.email_id, filename)

        matched_rule = _find_matching_rule(email, rules)

        if matched_rule:
            # --- Metadata match: download and read ---
            try:
                local_path = download_attachment(email.email_id, filename, matched_rule.vendor)
                reading = read_attachment(local_path)
            except Exception as exc:
                logger.warning("Failed processing attachment for %s: %s", matched_rule.vendor, exc)
                continue

            if reading.is_invoice:
                invoice_pool[pool_key] = (reading, email, local_path)
                direct_matches[matched_rule.vendor] = pool_key
        else:
            # --- Fallback: read attachment content for amount-based matching ---
            try:
                # We don't know the vendor yet; use a generic directory
                local_path = download_attachment(email.email_id, filename, "unknown")
                reading = read_attachment(local_path)
            except Exception as exc:
                logger.debug("Fallback download failed for email %s: %s", email.email_id, exc)
                continue

            if reading.is_invoice:
                invoice_pool[pool_key] = (reading, email, local_path)

        # Early exit: stop scanning when the pool already covers all transaction amounts
        pool_amount_counts: Counter[float] = Counter(
            r.amount for r, _, _ in invoice_pool.values() if r.amount is not None
        )
        if all(pool_amount_counts[a] >= n for a, n in tx_amount_counts.items()):
            logger.info("All transaction amounts covered; stopping email scan early.")
            break

    # --- Phase 7: amount-based matching ---
    # Group confirmed invoices by amount
    amount_index: dict[float, list[tuple[str, str]]] = defaultdict(list)
    for pool_key, (reading, _email, _path) in invoice_pool.items():
        if reading.amount is not None:
            amount_index[reading.amount].append(pool_key)

    results: list[InvoiceResult] = []
    claimed: set[tuple[str, str]] = set()

    for tx in transactions:
        try:
            result = _match_transaction(tx, amount_index, invoice_pool, claimed)
            results.append(result)
        except Exception as exc:
            logger.error("Unexpected error matching transaction %s: %s", tx.vendor, exc)
            results.append(
                InvoiceResult(
                    transaction=tx,
                    status="missing",
                    failure_reason=FailureReason.LLM_CALL_FAILED,
                    notes=str(exc),
                )
            )

    return results, ambiguous, derived_month


def _match_transaction(
    tx: Transaction,
    amount_index: dict[float, list[tuple[str, str]]],
    invoice_pool: dict[tuple[str, str], tuple[AttachmentReading, EmailMatch, Path]],
    claimed: set[tuple[str, str]],
) -> InvoiceResult:
    """Match a single transaction against the invoice pool."""
    candidates = [k for k in amount_index.get(tx.amount, []) if k not in claimed]

    if not candidates:
        return InvoiceResult(
            transaction=tx,
            status="missing",
            failure_reason=FailureReason.AMOUNT_MISMATCH,
        )

    if len(candidates) == 1:
        pool_key = candidates[0]
        _reading, email, local_path = invoice_pool[pool_key]
        claimed.add(pool_key)
        return InvoiceResult(
            transaction=tx,
            email_id=email.email_id,
            attachment_path=local_path,
            status="found",
        )

    # Multiple candidates — try vendor tiebreak
    vendor_matches = [k for k in candidates if _vendor_match(tx.vendor, invoice_pool[k][0].vendor)]

    if len(vendor_matches) == 1:
        pool_key = vendor_matches[0]
        _reading, email, local_path = invoice_pool[pool_key]
        claimed.add(pool_key)
        return InvoiceResult(
            transaction=tx,
            email_id=email.email_id,
            attachment_path=local_path,
            status="found",
        )

    return InvoiceResult(
        transaction=tx,
        status="missing",
        failure_reason=FailureReason.DUPLICATE_AMOUNT_VENDOR_MISMATCH,
    )
