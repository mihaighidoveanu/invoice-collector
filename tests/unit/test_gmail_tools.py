"""Tests for agent/gmail_tools.py — Gmail API always mocked."""

import base64
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from agent.gmail_tools import (
    _extract_attachment_filenames,
    _parse_message_metadata,
    _sanitize_dirname,
    download_attachment,
    list_emails_with_attachments,
)
from models import EmailMatch

# ---------------------------------------------------------------------------
# Helpers to build fake Gmail API payloads
# ---------------------------------------------------------------------------


def _make_msg(
    msg_id: str = "abc123",
    subject: str = "Invoice from Acme",
    sender: str = "billing@acme.com",
    snippet: str = "Please find attached",
    internal_date_ms: int = 1741132800000,  # 2025-03-05
    filenames: list[str] | None = None,
) -> dict:
    if filenames is None:
        filenames = ["invoice.pdf"]
    parts = [
        {"filename": fn, "body": {"attachmentId": f"att_{fn}"}, "parts": []} for fn in filenames
    ]
    return {
        "id": msg_id,
        "snippet": snippet,
        "internalDate": str(internal_date_ms),
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
            ],
            "parts": parts,
            "filename": "",
        },
    }


# ---------------------------------------------------------------------------
# _extract_attachment_filenames
# ---------------------------------------------------------------------------


def test_extract_attachment_filenames_flat():
    payload = {"filename": "invoice.pdf", "parts": []}
    assert _extract_attachment_filenames(payload) == ["invoice.pdf"]


def test_extract_attachment_filenames_nested():
    payload = {
        "filename": "",
        "parts": [
            {"filename": "a.pdf", "parts": []},
            {
                "filename": "",
                "parts": [{"filename": "b.pdf", "parts": []}],
            },
        ],
    }
    assert _extract_attachment_filenames(payload) == ["a.pdf", "b.pdf"]


def test_extract_attachment_filenames_empty():
    assert _extract_attachment_filenames({"filename": "", "parts": []}) == []


# ---------------------------------------------------------------------------
# _parse_message_metadata
# ---------------------------------------------------------------------------


def test_parse_message_metadata_returns_email_match():
    msg = _make_msg()
    result = _parse_message_metadata(msg)
    assert isinstance(result, EmailMatch)


def test_parse_message_metadata_fields():
    msg = _make_msg(subject="Your invoice", sender="accounts@acme.com")
    result = _parse_message_metadata(msg)
    assert result is not None
    assert result.subject == "Your invoice"
    assert result.sender == "accounts@acme.com"
    assert result.email_id == "abc123"
    assert result.attachment_filenames == ["invoice.pdf"]


def test_parse_message_metadata_no_attachments_returns_none():
    msg = _make_msg(filenames=[])
    result = _parse_message_metadata(msg)
    assert result is None


# ---------------------------------------------------------------------------
# _sanitize_dirname
# ---------------------------------------------------------------------------


def test_sanitize_dirname_normal():
    assert _sanitize_dirname("Amazon") == "Amazon"


def test_sanitize_dirname_spaces_preserved():
    assert _sanitize_dirname("Google Cloud") == "Google Cloud"


def test_sanitize_dirname_special_chars_replaced():
    result = _sanitize_dirname("Acme/Corp")
    assert "/" not in result


# ---------------------------------------------------------------------------
# list_emails_with_attachments
# ---------------------------------------------------------------------------


@patch("agent.gmail_tools._build_service")
def test_list_emails_returns_matches(mock_build_service):
    service = MagicMock()
    mock_build_service.return_value = service

    list_resp = {"messages": [{"id": "msg1"}]}
    service.users().messages().list().execute.return_value = list_resp
    service.users().messages().get().execute.return_value = _make_msg(msg_id="msg1")

    results = list_emails_with_attachments(date(2025, 3, 1), date(2025, 4, 1))

    assert len(results) == 1
    assert results[0].email_id == "msg1"


@patch("agent.gmail_tools._build_service")
def test_list_emails_no_messages_returns_empty(mock_build_service):
    service = MagicMock()
    mock_build_service.return_value = service
    service.users().messages().list().execute.return_value = {}

    results = list_emails_with_attachments(date(2025, 3, 1), date(2025, 4, 1))
    assert results == []


# ---------------------------------------------------------------------------
# download_attachment
# ---------------------------------------------------------------------------


@patch("agent.gmail_tools._build_service")
def test_download_attachment_writes_file(mock_build_service, tmp_path):
    service = MagicMock()
    mock_build_service.return_value = service

    fake_data = b"%PDF-1.4 fake content"
    encoded = base64.urlsafe_b64encode(fake_data).decode()

    service.users().messages().get().execute.return_value = _make_msg(
        msg_id="msg1", filenames=["invoice.pdf"]
    )
    service.users().messages().attachments().get().execute.return_value = {"data": encoded}

    with patch("agent.gmail_tools.settings") as mock_settings:
        mock_settings.invoice_output_dir = tmp_path
        mock_settings.gmail_scopes_list = ["https://www.googleapis.com/auth/gmail.readonly"]

        dest = download_attachment("msg1", "invoice.pdf", "Acme")

    assert dest.exists()
    assert dest.read_bytes() == fake_data


@patch("agent.gmail_tools._build_service")
def test_download_attachment_missing_filename_raises(mock_build_service):
    service = MagicMock()
    mock_build_service.return_value = service

    service.users().messages().get().execute.return_value = _make_msg(
        msg_id="msg1", filenames=["other.pdf"]
    )

    with pytest.raises(ValueError, match="not found"):
        download_attachment("msg1", "invoice.pdf", "Acme")
