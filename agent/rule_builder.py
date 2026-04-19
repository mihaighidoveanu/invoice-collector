"""Phase 2 — Rule builder.

Fully deterministic: builds Gmail search rules from transactions.
No LLM calls.
"""

from models import Transaction, VendorRule

_VENDOR_STOPWORDS = {"srl", "sa", "ltd", "inc", "sc", "srls"}

INVOICE_INDICATOR_KEYWORDS = [
    "invoice", "factura", "receipt", "bill", "bon fiscal",
    "proforma", "chitanta", "plata", "payment",
]


def _vendor_tokens(vendor: str) -> list[str]:
    """Split vendor name into lowercase tokens, filtering short words and legal-form stopwords."""
    toks = [t for t in vendor.lower().split() if len(t) >= 3 and t not in _VENDOR_STOPWORDS]
    return list(dict.fromkeys(toks))  # dedupe, preserve order


def build_vendor_rule(transaction: Transaction) -> VendorRule:
    """Build a VendorRule for a single transaction."""
    tokens = _vendor_tokens(transaction.vendor)
    return VendorRule(vendor=transaction.vendor, sender_keywords=tokens)


def build_vendor_rules(transactions: list[Transaction]) -> list[VendorRule]:
    """Build a VendorRule for every transaction."""
    return [build_vendor_rule(tx) for tx in transactions]
