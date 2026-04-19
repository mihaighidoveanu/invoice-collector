"""Shared fixtures for real-data tests.

Requires a real bank statement PDF:
    TEST_STATEMENT_PDF=invoices/statement.pdf pytest tests/real -v -s
"""

import os
from pathlib import Path

import pytest

from agent.gmail_tools import download_attachment, list_emails_with_attachments
from agent.pipeline import _analysis_window, _derive_target_month, run_pipeline
from agent.rule_builder import build_rules
from agent.statement_parser import parse_statement
from models import EmailMatch, InvoiceResult, SearchRule, Transaction


@pytest.fixture(scope="session")
def statement_pdf() -> Path:
    path = os.environ.get("TEST_STATEMENT_PDF")
    if not path:
        pytest.skip("TEST_STATEMENT_PDF environment variable not set")
    pdf = Path(path)
    if not pdf.exists():
        pytest.skip(f"Statement PDF not found: {pdf}")
    return pdf


@pytest.fixture(scope="session")
def real_parse_result(statement_pdf) -> list[Transaction]:
    return parse_statement(statement_pdf)


@pytest.fixture(scope="session")
def real_transactions(real_parse_result) -> list[Transaction]:
    return real_parse_result


@pytest.fixture(scope="session")
def real_rules(real_transactions) -> list[SearchRule]:
    return build_rules(real_transactions)


@pytest.fixture(scope="session")
def real_emails(real_transactions) -> list[EmailMatch]:
    target_month = _derive_target_month(real_transactions)
    start, end = _analysis_window(target_month)
    return list_emails_with_attachments(start, end)


@pytest.fixture(scope="session")
def real_first_attachment(real_emails, tmp_path_factory) -> Path:
    """Downloads the first PDF attachment found in the fetched emails."""
    for email in real_emails:
        for filename in email.attachment_filenames:
            if filename.lower().endswith(".pdf"):
                tmp_dir = tmp_path_factory.mktemp("attachments")
                return download_attachment(email.email_id, filename, "test_fixture")
    pytest.skip("No PDF attachments found in fetched emails")


@pytest.fixture(scope="session")
def real_pipeline_results(
    statement_pdf, tmp_path_factory
) -> tuple[list[InvoiceResult], str]:
    run_dir = tmp_path_factory.mktemp("pipeline_run")
    return run_pipeline(statement_pdf, run_dir=run_dir)
