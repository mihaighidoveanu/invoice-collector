"""Tests for agent/report_builder.py."""

import json
from datetime import date

from agent.report_builder import build_report
from models import (
    FailureReason,
    InvoiceResult,
    Transaction,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _tx(vendor: str, amount: float = 29.99) -> Transaction:
    return Transaction(
        vendor=vendor,
        amount=amount,
        date=date(2025, 3, 5),
        raw_description=f"RAW {vendor.upper()}",
    )


def _found(vendor: str, amount: float = 29.99) -> InvoiceResult:
    return InvoiceResult(
        transaction=_tx(vendor, amount),
        email_id="e1",
        status="found",
    )


def _missing(vendor: str, reason: FailureReason = FailureReason.AMOUNT_MISMATCH) -> InvoiceResult:
    return InvoiceResult(
        transaction=_tx(vendor),
        status="missing",
        failure_reason=reason,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_report_counts(tmp_path):
    results = [_found("Amazon"), _missing("Zoom"), _found("Netflix")]
    report = build_report(results, "2025-03", output_path=tmp_path / "report.json")

    assert report.invoices_found == 2
    assert report.invoices_missing == 1


def test_build_report_writes_json_file(tmp_path):
    out = tmp_path / "report_2025-03.json"
    build_report([_found("Amazon")], "2025-03", output_path=out)

    assert out.exists()
    data = json.loads(out.read_text())
    assert data["target_month"] == "2025-03"
    assert data["invoices_found"] == 1


def test_build_report_errors_list(tmp_path):
    results = [
        _found("Amazon"),
        _missing("Zoom", FailureReason.AMOUNT_MISMATCH),
        _missing("Slack", FailureReason.DUPLICATE_AMOUNT_VENDOR_MISMATCH),
    ]
    report = build_report(results, "2025-03", output_path=tmp_path / "report.json")

    assert len(report.errors) == 2
    assert any("Zoom" in e for e in report.errors)
    assert any("Slack" in e for e in report.errors)


def test_build_report_json_structure(tmp_path):
    out = tmp_path / "report.json"
    results = [_found("Amazon"), _missing("Zoom")]
    build_report(results, "2025-03", output_path=out)

    data = json.loads(out.read_text())
    assert "run_date" in data
    assert "results" in data
    assert "errors" in data
    assert isinstance(data["results"], list)
    assert len(data["results"]) == 2


def test_build_report_run_date_is_today(tmp_path):
    report = build_report([], "2025-03", output_path=tmp_path / "r.json")
    assert report.run_date == date.today()
