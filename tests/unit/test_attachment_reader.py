"""Tests for agent/attachment_reader.py — LLM always mocked."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.attachment_reader import _parse_llm_response, read_attachment

# ---------------------------------------------------------------------------
# Sample LLM responses
# ---------------------------------------------------------------------------

INVOICE_RESPONSE = json.dumps(
    {
        "is_invoice": True,
        "vendor": "Acme Corp",
        "amount": 150.00,
        "date": "2025-03-10",
        "confidence": 0.97,
    }
)

NOT_INVOICE_RESPONSE = json.dumps({"is_invoice": False})


# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------


def test_parse_llm_response_invoice():
    result = _parse_llm_response(INVOICE_RESPONSE)
    assert result.is_invoice is True
    assert result.vendor == "Acme Corp"
    assert result.amount == pytest.approx(150.00)
    assert str(result.invoice_date) == "2025-03-10"
    assert result.confidence == pytest.approx(0.97)


def test_parse_llm_response_not_invoice():
    result = _parse_llm_response(NOT_INVOICE_RESPONSE)
    assert result.is_invoice is False
    assert result.vendor is None
    assert result.amount is None


def test_parse_llm_response_strips_markdown():
    wrapped = f"```json\n{INVOICE_RESPONSE}\n```"
    result = _parse_llm_response(wrapped)
    assert result.is_invoice is True


# ---------------------------------------------------------------------------
# read_attachment — short text gate (no LLM)
# ---------------------------------------------------------------------------


@patch("agent.attachment_reader._extract_text")
def test_read_attachment_short_text_skips_llm(mock_extract):
    mock_extract.return_value = "short"  # < 50 chars

    result = read_attachment(Path("short.pdf"))

    assert result.is_invoice is False
    assert result.vendor is None


# ---------------------------------------------------------------------------
# read_attachment — full text invoice (LLM mocked)
# ---------------------------------------------------------------------------


@patch("agent.attachment_reader._extract_text")
@patch("agent.attachment_reader._build_llm")
def test_read_attachment_invoice_detected(mock_build_llm, mock_extract):
    mock_extract.return_value = "A" * 100  # >= 50 chars
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=INVOICE_RESPONSE)
    mock_build_llm.return_value = mock_llm

    result = read_attachment(Path("invoice.pdf"))

    assert result.is_invoice is True
    assert result.vendor == "Acme Corp"
    mock_llm.invoke.assert_called_once()


@patch("agent.attachment_reader._extract_text")
@patch("agent.attachment_reader._build_llm")
def test_read_attachment_not_invoice(mock_build_llm, mock_extract):
    mock_extract.return_value = "B" * 100
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=NOT_INVOICE_RESPONSE)
    mock_build_llm.return_value = mock_llm

    result = read_attachment(Path("contract.pdf"))

    assert result.is_invoice is False


@patch("agent.attachment_reader._extract_text")
@patch("agent.attachment_reader._build_llm")
def test_read_attachment_llm_failure_returns_not_invoice(mock_build_llm, mock_extract):
    mock_extract.return_value = "C" * 100
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("LLM down")
    mock_build_llm.return_value = mock_llm

    result = read_attachment(Path("invoice.pdf"))

    assert result.is_invoice is False


@patch("agent.attachment_reader._extract_text")
def test_read_attachment_pdfplumber_failure_returns_not_invoice(mock_extract):
    mock_extract.side_effect = Exception("corrupt PDF")

    result = read_attachment(Path("corrupt.pdf"))

    assert result.is_invoice is False
