"""Tests for agent/statement_parser.py — LLM is always mocked."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.statement_parser import _parse_llm_response, parse_statement
from models import Transaction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_LLM_RESPONSE = json.dumps(
    [
        {
            "raw_description": "AMZN MKTP US*AB12",
            "vendor": "Amazon",
            "amount": 29.99,

            "date": "2025-03-05",
        },
        {
            "raw_description": "GOOGLE *CLOUD",
            "vendor": "Google Cloud",
            "amount": 120.00,

            "date": "2025-03-10",
        },
        {
            "raw_description": "SQ *COFFEE SHOP",
            "vendor": "Square Coffee Shop",
            "amount": 8.50,

            "date": "2025-03-12",
        },
        {
            "raw_description": "NETFLIX.COM",
            "vendor": "Netflix",
            "amount": 15.99,

            "date": "2025-03-18",
        },
        {
            "raw_description": "DROPBOX INC",
            "vendor": "Dropbox",
            "amount": 9.99,

            "date": "2025-03-22",
        },
    ]
)


# ---------------------------------------------------------------------------
# Unit tests: _parse_llm_response
# ---------------------------------------------------------------------------


def test_parse_llm_response_returns_transactions():
    transactions = _parse_llm_response(SAMPLE_LLM_RESPONSE)

    assert len(transactions) == 5
    assert all(isinstance(t, Transaction) for t in transactions)


def test_parse_llm_response_vendor_names():
    transactions = _parse_llm_response(SAMPLE_LLM_RESPONSE)
    vendors = [t.vendor for t in transactions]
    assert "Amazon" in vendors
    assert "Google Cloud" in vendors
    assert "Netflix" in vendors


def test_parse_llm_response_strips_markdown_fences():
    wrapped = f"```json\n{SAMPLE_LLM_RESPONSE}\n```"
    transactions = _parse_llm_response(wrapped)
    assert len(transactions) == 5


def test_parse_llm_response_amounts_and_dates():
    transactions = _parse_llm_response(SAMPLE_LLM_RESPONSE)
    amazon = next(t for t in transactions if t.vendor == "Amazon")
    assert amazon.amount == pytest.approx(29.99)
    assert str(amazon.date) == "2025-03-05"


# ---------------------------------------------------------------------------
# Integration test: parse_statement (LLM mocked)
# ---------------------------------------------------------------------------


@patch("agent.statement_parser._extract_text")
@patch("agent.statement_parser._build_llm")
def test_parse_statement_returns_transactions(mock_build_llm, mock_extract_text):
    mock_extract_text.return_value = "dummy bank text"
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=SAMPLE_LLM_RESPONSE)
    mock_build_llm.return_value = mock_llm

    transactions = parse_statement(Path("dummy.pdf"))

    assert len(transactions) == 5
    mock_llm.invoke.assert_called_once()


@patch("agent.statement_parser._extract_text")
@patch("agent.statement_parser._build_llm")
def test_parse_statement_llm_failure_returns_empty(mock_build_llm, mock_extract_text):
    mock_extract_text.return_value = "dummy bank text"
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API error")
    mock_build_llm.return_value = mock_llm

    transactions = parse_statement(Path("dummy.pdf"))

    assert transactions == []


@patch("agent.statement_parser._extract_text")
@patch("agent.statement_parser._build_llm")
def test_parse_statement_malformed_json_returns_empty(mock_build_llm, mock_extract_text):
    mock_extract_text.return_value = "dummy bank text"
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="not valid json {{{")
    mock_build_llm.return_value = mock_llm

    transactions = parse_statement(Path("dummy.pdf"))

    assert transactions == []
