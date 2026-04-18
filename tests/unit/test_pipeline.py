"""Integration tests for agent/pipeline.py.

All external I/O (statement parser, Gmail, LLM) is mocked.
"""

from datetime import date
from pathlib import Path
from unittest.mock import patch

from agent.pipeline import _analysis_window, _derive_target_month, run_pipeline
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
        currency="USD",
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
    assert end == date(2025, 5, 1)


def test_analysis_window_december_wraps_year():
    start, end = _analysis_window("2025-12")
    assert start == date(2025, 12, 1)
    assert end == date(2026, 2, 1)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@patch("agent.pipeline.read_attachment")
@patch("agent.pipeline.download_attachment")
@patch("agent.pipeline.list_emails_with_attachments")
@patch("agent.pipeline.parse_statement")
def test_unique_amount_match(mock_parse, mock_list_emails, mock_download, mock_read):
    """Clean unique-amount match → status='found'."""
    transactions = [_tx("Amazon", 29.99)]
    mock_parse.return_value = (transactions, [])
    mock_list_emails.return_value = [_email("e1", subject="Amazon invoice")]
    mock_download.return_value = Path("/tmp/invoice.pdf")
    mock_read.return_value = _reading("Amazon", 29.99)

    results, _, month = run_pipeline(Path("statement.pdf"), target_month="2025-03")

    assert len(results) == 1
    assert results[0].status == "found"
    assert results[0].transaction.vendor == "Amazon"
    assert results[0].attachment_path == Path("/tmp/invoice.pdf")


@patch("agent.pipeline.read_attachment")
@patch("agent.pipeline.download_attachment")
@patch("agent.pipeline.list_emails_with_attachments")
@patch("agent.pipeline.parse_statement")
def test_no_email_match_returns_missing(mock_parse, mock_list_emails, mock_download, mock_read):
    """No emails found → status='missing' with AMOUNT_MISMATCH."""
    transactions = [_tx("Zoom", 14.99)]
    mock_parse.return_value = (transactions, [])
    mock_list_emails.return_value = []

    results, _, _ = run_pipeline(Path("statement.pdf"), target_month="2025-03")

    assert results[0].status == "missing"
    assert results[0].failure_reason == FailureReason.AMOUNT_MISMATCH


@patch("agent.pipeline.read_attachment")
@patch("agent.pipeline.download_attachment")
@patch("agent.pipeline.list_emails_with_attachments")
@patch("agent.pipeline.parse_statement")
def test_duplicate_amount_vendor_tiebreak_success(
    mock_parse, mock_list_emails, mock_download, mock_read
):
    """Two invoices with same amount; vendor tiebreak resolves → found."""
    transactions = [_tx("Netflix", 15.99)]
    mock_parse.return_value = (transactions, [])
    mock_list_emails.return_value = [
        _email("e1", subject="Netflix invoice"),
        _email("e2", subject="Other invoice"),
    ]
    mock_download.return_value = Path("/tmp/invoice.pdf")

    def read_side_effect(path: Path) -> AttachmentReading:
        # The second call returns a reading for a different vendor
        if not hasattr(read_side_effect, "_count"):
            read_side_effect._count = 0
        read_side_effect._count += 1
        if read_side_effect._count == 1:
            return _reading("Netflix", 15.99)
        return _reading("Hulu", 15.99)

    mock_read.side_effect = read_side_effect

    results, _, _ = run_pipeline(Path("statement.pdf"), target_month="2025-03")

    assert results[0].status == "found"


@patch("agent.pipeline.read_attachment")
@patch("agent.pipeline.download_attachment")
@patch("agent.pipeline.list_emails_with_attachments")
@patch("agent.pipeline.parse_statement")
def test_duplicate_amount_vendor_tiebreak_fails(
    mock_parse, mock_list_emails, mock_download, mock_read
):
    """Two transactions at same amount, two invoices with non-matching vendors → both missing.

    Two transactions force the early-exit check to require two pool entries before stopping,
    so both emails are downloaded and both end up as duplicate candidates with no vendor match.
    """
    transactions = [_tx("Netflix", 15.99), _tx("Spotify", 15.99)]
    mock_parse.return_value = (transactions, [])
    mock_list_emails.return_value = [
        _email("e1", subject="Hulu invoice"),
        _email("e2", subject="Disney invoice"),
    ]
    mock_download.return_value = Path("/tmp/invoice.pdf")
    mock_read.side_effect = [
        _reading("Hulu", 15.99),
        _reading("Disney", 15.99),
    ]

    results, _, _ = run_pipeline(Path("statement.pdf"), target_month="2025-03")

    assert all(r.status == "missing" for r in results)
    assert all(r.failure_reason == FailureReason.DUPLICATE_AMOUNT_VENDOR_MISMATCH for r in results)


@patch("agent.pipeline.parse_statement")
def test_no_transactions_returns_empty(mock_parse):
    """If parser returns nothing, pipeline returns empty."""
    mock_parse.return_value = ([], [])

    results, ambiguous, _ = run_pipeline(Path("statement.pdf"), target_month="2025-03")

    assert results == []
    assert ambiguous == []
