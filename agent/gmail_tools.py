"""Phase 3 — Gmail tools.

OAuth2 browser flow on first run, silent refresh on subsequent runs.
"""

import base64
import logging
from datetime import date
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import settings
from models import EmailMatch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _get_credentials() -> Credentials:
    """Return valid OAuth2 credentials, running browser flow if needed."""
    creds: Credentials | None = None
    token_path = settings.gmail_token_path
    scopes = settings.gmail_scopes_list

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(settings.gmail_credentials_path), scopes
            )
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return creds


def _build_service():
    """Build and return a Gmail API service object."""
    creds = _get_credentials()
    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_emails_with_attachments(after: date, before: date) -> list[EmailMatch]:
    """Fetch metadata for all emails with attachments in the given date range.

    Args:
        after: Start of the range (inclusive), formatted as YYYY/MM/DD in the query.
        before: End of the range (exclusive), formatted as YYYY/MM/DD in the query.

    Returns:
        List of EmailMatch objects with metadata only (no downloads).
    """
    query = (
        f"has:attachment after:{after.strftime('%Y/%m/%d')} "
        f"before:{before.strftime('%Y/%m/%d')}"
    )
    logger.info("Gmail query: %s", query)

    service = _build_service()
    matches: list[EmailMatch] = []

    try:
        response = service.users().messages().list(userId="me", q=query).execute()
        messages = response.get("messages", [])

        for msg_stub in messages:
            msg_id = msg_stub["id"]
            try:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_id, format="metadata")
                    .execute()
                )
                match = _parse_message_metadata(msg)
                if match is not None:
                    matches.append(match)
            except HttpError as exc:
                logger.warning("Failed to fetch message %s: %s", msg_id, exc)

    except HttpError as exc:
        logger.error("Gmail list request failed: %s", exc)

    logger.info("Found %d emails with attachments", len(matches))
    return matches


def download_attachment(email_id: str, filename: str, vendor: str) -> Path:
    """Download a specific attachment and save it under the vendor's directory.

    Args:
        email_id: Gmail message ID.
        filename: Attachment filename to download.
        vendor: Vendor name used to determine the output subdirectory.

    Returns:
        Local path where the attachment was saved.
    """
    service = _build_service()

    msg = service.users().messages().get(userId="me", id=email_id, format="full").execute()

    attachment_id = _find_attachment_id(msg, filename)
    if attachment_id is None:
        raise ValueError(f"Attachment '{filename}' not found in message {email_id}")

    attachment = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=email_id, id=attachment_id)
        .execute()
    )

    data = base64.urlsafe_b64decode(attachment["data"])

    vendor_dir = settings.invoice_output_dir / _sanitize_dirname(vendor)
    vendor_dir.mkdir(parents=True, exist_ok=True)

    dest = vendor_dir / filename
    dest.write_bytes(data)
    logger.info("Downloaded attachment to %s", dest)
    return dest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_message_metadata(msg: dict) -> EmailMatch | None:
    """Extract EmailMatch from a Gmail API message resource (metadata format)."""
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    subject = headers.get("subject", "")
    sender = headers.get("from", "")
    internal_date_ms = int(msg.get("internalDate", 0))
    msg_date = date.fromtimestamp(internal_date_ms / 1000)
    snippet = msg.get("snippet", "")

    attachment_filenames = _extract_attachment_filenames(msg.get("payload", {}))

    if not attachment_filenames:
        return None

    return EmailMatch(
        email_id=msg["id"],
        subject=subject,
        sender=sender,
        snippet=snippet,
        attachment_filenames=attachment_filenames,
        date=msg_date,
    )


def _extract_attachment_filenames(payload: dict) -> list[str]:
    """Recursively extract attachment filenames from a message payload."""
    filenames: list[str] = []
    if payload.get("filename"):
        filenames.append(payload["filename"])
    for part in payload.get("parts", []):
        filenames.extend(_extract_attachment_filenames(part))
    return filenames


def _find_attachment_id(msg: dict, filename: str) -> str | None:
    """Recursively find the attachment ID for a given filename."""
    payload = msg.get("payload", {})
    return _search_attachment_id(payload, filename)


def _search_attachment_id(part: dict, filename: str) -> str | None:
    if part.get("filename") == filename:
        body = part.get("body", {})
        return body.get("attachmentId")
    for sub in part.get("parts", []):
        result = _search_attachment_id(sub, filename)
        if result is not None:
            return result
    return None


def _sanitize_dirname(name: str) -> str:
    """Convert a vendor name into a safe directory name."""
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
