from datetime import date
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class Transaction(BaseModel):
    vendor: str
    amount: float
    date: date
    raw_description: str


class VendorRule(BaseModel):
    vendor: str
    sender_keywords: list[str]


class EmailMatch(BaseModel):
    email_id: str
    subject: str
    sender: str
    snippet: str
    attachment_filenames: list[str]
    date: date


class AttachmentReading(BaseModel):
    is_invoice: bool
    vendor: str | None = None
    amount: float | None = None
    invoice_date: date | None = None
    confidence: float | None = None


class FailureReason(str, Enum):
    AMOUNT_MISMATCH = "No invoice with a matching amount found in the analysis period"
    DUPLICATE_AMOUNT_VENDOR_MISMATCH = (
        "Multiple invoices share the same amount; vendor name matching failed to resolve"
    )
    LLM_CALL_FAILED = "LLM call failed after all retries"
    ATTACHMENT_NOT_INVOICE = "Downloaded attachment is not an invoice"
    ATTACHMENT_UNREADABLE = "Attachment PDF has insufficient text (scanned/image PDF)"
    NO_ATTACHMENTS_IN_EMAIL = "Matched email has no downloadable attachments"


class InvoiceResult(BaseModel):
    transaction: Transaction
    email_id: str | None = None
    attachment_path: Path | None = None
    status: Literal["found", "missing"]
    failure_reason: FailureReason | None = None
    notes: str | None = None
