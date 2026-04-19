"""Unit tests for agent/pipeline.py.

All external I/O (statement parser, Gmail, LLM, PDF extraction) is mocked.
"""

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.pipeline import (
    _amount_strings,
    _analysis_window,
    _assign_to_transaction,
    _build_amount_lookup,
    _derive_target_month,
    run_pipeline,
)
from models import (
    AttachmentReading,
    EmailMatch,
    FailureReason,
    Transaction,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tx(vendor: str, amount: float, tx_date: date = date(2025, 3, 5)) -> Transaction:
    return Transaction(
        vendor=vendor,
        amount=amount,
        date=tx_date,
        raw_description=f"RAW {vendor.upper()}",
    )


def _email(
    email_id: str,
    subject: str = "",
    filenames: list[str] | None = None,
    sender: str = "billing@vendor.com",
    email_date: date = date(2025, 3, 10),
) -> EmailMatch:
    return EmailMatch(
        email_id=email_id,
        subject=subject,
        sender=sender,
        snippet="",
        attachment_filenames=filenames or ["invoice.pdf"],
        date=email_date,
    )


def _reading(vendor: str, amount: float) -> AttachmentReading:
    return AttachmentReading(
        is_invoice=True,
        vendor=vendor,
        amount=amount,
        invoice_date=date(2025, 3, 10),
        confidence=0.95,
    )


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


def test_derive_target_month():
    txs = [
        _tx("Amazon", 10.0, date(2025, 3, 1)),
        _tx("Google", 20.0, date(2025, 3, 15)),
        _tx("Netflix", 5.0, date(2025, 4, 1)),
    ]
    assert _derive_target_month(txs) == "2025-03"


def test_analysis_window_march():
    start, end = _analysis_window("2025-03")
    assert start == date(2025, 3, 1)
    assert end == date(2025, 4, 6)  # 2025-03-31 + 6 days (exclusive, covers through +5)


def test_analysis_window_december_wraps_year():
    start, end = _analysis_window("2025-12")
    assert start == date(2025, 12, 1)
    assert end == date(2026, 1, 6)  # 2025-12-31 + 6 days


# ---------------------------------------------------------------------------
# _amount_strings
# ---------------------------------------------------------------------------


def test_amount_strings_simple():
    strs = _amount_strings(29.99)
    assert "29.99" in strs
    assert "29,99" in strs


def test_amount_strings_thousands_eu():
    strs = _amount_strings(1500.00)
    assert "1.500,00" in strs


def test_amount_strings_thousands_us():
    strs = _amount_strings(1500.00)
    assert "1,500.00" in strs


def test_amount_strings_below_thousand_no_separator():
    strs = _amount_strings(999.99)
    assert "999.99" in strs
    assert not any("." in s and "," in s for s in strs)


# ---------------------------------------------------------------------------
# _build_amount_lookup
# ---------------------------------------------------------------------------


def test_build_amount_lookup_maps_to_indices():
    txs = [_tx("Amazon", 29.99), _tx("Netflix", 15.99)]
    lookup = _build_amount_lookup(txs)
    assert 0 in lookup["29.99"]
    assert 1 in lookup["15.99"]


def test_build_amount_lookup_all_encodings_present():
    txs = [_tx("Vendor", 1500.00)]
    lookup = _build_amount_lookup(txs)
    assert 0 in lookup["1500.00"]
    assert 0 in lookup["1500,00"]
    assert 0 in lookup["1.500,00"]
    assert 0 in lookup["1,500.00"]


# ---------------------------------------------------------------------------
# _assign_to_transaction
# ---------------------------------------------------------------------------


def test_assign_unique_amount_match():
    txs = [_tx("Amazon", 29.99)]
    lookup = _build_amount_lookup(txs)
    reading = _reading("Amazon", 29.99)
    result = _assign_to_transaction(reading, ["29.99"], None, txs, set(), lookup)
    assert result == 0


def test_assign_candidate_vendor_tiebreak():
    txs = [_tx("Amazon", 15.99), _tx("Netflix", 15.99)]
    lookup = _build_amount_lookup(txs)
    reading = _reading("Amazon", 15.99)
    result = _assign_to_transaction(reading, ["15.99"], "Amazon", txs, set(), lookup)
    assert result == 0


def test_assign_no_match_returns_none():
    txs = [_tx("Amazon", 29.99)]
    lookup = _build_amount_lookup(txs)
    reading = _reading("Amazon", 99.99)
    result = _assign_to_transaction(reading, ["99.99"], None, txs, set(), lookup)
    assert result is None


def test_assign_already_claimed_returns_none():
    txs = [_tx("Amazon", 29.99)]
    lookup = _build_amount_lookup(txs)
    reading = _reading("Amazon", 29.99)
    result = _assign_to_transaction(reading, ["29.99"], None, txs, {0}, lookup)
    assert result is None


def test_assign_ambiguous_without_vendor_returns_none():
    txs = [_tx("Netflix", 15.99), _tx("Spotify", 15.99)]
    lookup = _build_amount_lookup(txs)
    reading = AttachmentReading(is_invoice=True, amount=15.99)
    result = _assign_to_transaction(reading, ["15.99"], None, txs, set(), lookup)
    assert result is None


# ---------------------------------------------------------------------------
# run_pipeline — integration tests (all external I/O mocked)
# ---------------------------------------------------------------------------


@patch("agent.pipeline.extract_text")
@patch("agent.pipeline.read_attachment")
@patch("agent.pipeline.download_attachment")
@patch("agent.pipeline.list_emails_with_attachments")
@patch("agent.pipeline.build_gmail_query")
@patch("agent.pipeline.parse_statement")
def test_unique_amount_match(
    mock_parse, mock_query, mock_list_emails, mock_download, mock_read, mock_extract
):
    """Clean unique-amount match → status='found'."""
    transactions = [_tx("Amazon", 29.99)]
    mock_parse.return_value = transactions
    mock_query.return_value = "has:attachment"
    mock_list_emails.return_value = [_email("e1", subject="Amazon invoice")]
    mock_download.return_value = Path("/tmp/invoice.pdf")
    mock_extract.return_value = "Invoice total: 29.99 EUR"
    mock_read.return_value = _reading("Amazon", 29.99)

    results, month = run_pipeline(Path("statement.pdf"), target_month="2025-03")

    assert len(results) == 1
    assert results[0].status == "found"
    assert results[0].transaction.vendor == "Amazon"
    assert results[0].attachment_path == Path("/tmp/invoice.pdf")


@patch("agent.pipeline.extract_text")
@patch("agent.pipeline.read_attachment")
@patch("agent.pipeline.download_attachment")
@patch("agent.pipeline.list_emails_with_attachments")
@patch("agent.pipeline.build_gmail_query")
@patch("agent.pipeline.parse_statement")
def test_no_email_match_returns_missing(
    mock_parse, mock_query, mock_list_emails, mock_download, mock_read, mock_extract
):
    """No emails found → status='missing' with AMOUNT_MISMATCH."""
    transactions = [_tx("Zoom", 14.99)]
    mock_parse.return_value = transactions
    mock_query.return_value = "has:attachment"
    mock_list_emails.return_value = []

    results, _ = run_pipeline(Path("statement.pdf"), target_month="2025-03")

    assert results[0].status == "missing"
    assert results[0].failure_reason == FailureReason.AMOUNT_MISMATCH


@patch("agent.pipeline.extract_text")
@patch("agent.pipeline.read_attachment")
@patch("agent.pipeline.download_attachment")
@patch("agent.pipeline.list_emails_with_attachments")
@patch("agent.pipeline.build_gmail_query")
@patch("agent.pipeline.parse_statement")
def test_amount_gate_skips_non_matching_pdf(
    mock_parse, mock_query, mock_list_emails, mock_download, mock_read, mock_extract
):
    """PDF without matching amount → LLM not called, tx stays missing."""
    transactions = [_tx("Amazon", 29.99)]
    mock_parse.return_value = transactions
    mock_query.return_value = "has:attachment"
    mock_list_emails.return_value = [_email("e1")]
    mock_download.return_value = Path("/tmp/invoice.pdf")
    mock_extract.return_value = "No relevant amount here"  # no "29.99" in text

    results, _ = run_pipeline(Path("statement.pdf"), target_month="2025-03")

    mock_read.assert_not_called()
    assert results[0].status == "missing"


@patch("agent.pipeline.extract_text")
@patch("agent.pipeline.read_attachment")
@patch("agent.pipeline.download_attachment")
@patch("agent.pipeline.list_emails_with_attachments")
@patch("agent.pipeline.build_gmail_query")
@patch("agent.pipeline.parse_statement")
def test_duplicate_amount_vendor_tiebreak_success(
    mock_parse, mock_query, mock_list_emails, mock_download, mock_read, mock_extract
):
    """Two invoices with same amount; sender vendor tiebreak resolves → found."""
    transactions = [_tx("Netflix", 15.99)]
    mock_parse.return_value = transactions
    mock_query.return_value = "has:attachment"
    mock_list_emails.return_value = [
        _email("e1", sender="billing@netflix.com"),
        _email("e2", sender="billing@hulu.com"),
    ]
    mock_download.return_value = Path("/tmp/invoice.pdf")
    mock_extract.return_value = "Amount: 15.99"
    mock_read.side_effect = [_reading("Netflix", 15.99), _reading("Hulu", 15.99)]

    results, _ = run_pipeline(Path("statement.pdf"), target_month="2025-03")

    assert results[0].status == "found"


@patch("agent.pipeline.extract_text")
@patch("agent.pipeline.read_attachment")
@patch("agent.pipeline.download_attachment")
@patch("agent.pipeline.list_emails_with_attachments")
@patch("agent.pipeline.build_gmail_query")
@patch("agent.pipeline.parse_statement")
def test_duplicate_amount_ambiguous_both_missing(
    mock_parse, mock_query, mock_list_emails, mock_download, mock_read, mock_extract
):
    """Two txs at same amount, two non-matching invoices → both missing."""
    transactions = [_tx("Netflix", 15.99), _tx("Spotify", 15.99)]
    mock_parse.return_value = transactions
    mock_query.return_value = "has:attachment"
    mock_list_emails.return_value = [
        _email("e1", sender="billing@hulu.com"),
        _email("e2", sender="billing@disney.com"),
    ]
    mock_download.return_value = Path("/tmp/invoice.pdf")
    mock_extract.return_value = "Amount: 15.99"
    mock_read.side_effect = [
        _reading("Hulu", 15.99),
        _reading("Disney", 15.99),
    ]

    results, _ = run_pipeline(Path("statement.pdf"), target_month="2025-03")

    assert all(r.status == "missing" for r in results)
    assert all(r.failure_reason == FailureReason.AMOUNT_MISMATCH for r in results)


@patch("agent.pipeline.parse_statement")
def test_no_transactions_returns_empty(mock_parse):
    """If parser returns nothing, pipeline returns empty."""
    mock_parse.return_value = []

    results, _ = run_pipeline(Path("statement.pdf"), target_month="2025-03")

    assert results == []


@patch("agent.pipeline.extract_text")
@patch("agent.pipeline.read_attachment")
@patch("agent.pipeline.download_attachment")
@patch("agent.pipeline.list_emails_with_attachments")
@patch("agent.pipeline.build_gmail_query")
@patch("agent.pipeline.parse_statement")
def test_early_exit_when_all_transactions_claimed(
    mock_parse, mock_query, mock_list_emails, mock_download, mock_read, mock_extract
):
    """Pipeline stops scanning emails once all transactions are matched."""
    transactions = [_tx("Amazon", 29.99)]
    mock_parse.return_value = transactions
    mock_query.return_value = "has:attachment"
    mock_list_emails.return_value = [
        _email("e1"),
        _email("e2"),  # should never be processed
    ]
    mock_download.return_value = Path("/tmp/invoice.pdf")
    mock_extract.return_value = "Amount: 29.99"
    mock_read.return_value = _reading("Amazon", 29.99)

    results, _ = run_pipeline(Path("statement.pdf"), target_month="2025-03")

    assert results[0].status == "found"
    assert mock_download.call_count == 1  # only one email processed
