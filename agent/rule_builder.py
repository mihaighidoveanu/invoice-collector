"""Phase 2 — Rule builder.

Fully deterministic: builds Gmail search rules from transactions.
No LLM calls.
"""

from models import Transaction, VendorRule

_VENDOR_STOPWORDS = {"srl", "sa", "ltd", "inc", "sc", "srls"}

# Extra sender domains for vendors whose billing emails use a different domain than their name.
_VENDOR_SENDER_ALIASES: dict[str, list[str]] = {
    "claude.ai": ["anthropic"],
}

INVOICE_INDICATOR_KEYWORDS = [
    "invoice", "factura", "receipt", "bill", "bon fiscal",
    "proforma", "chitanta", "plata", "payment",
]


def _vendor_tokens(vendor: str) -> list[str]:
    """Split vendor name into lowercase tokens, filtering short words and legal-form stopwords."""
    toks = [t for t in vendor.lower().split() if len(t) >= 5 and t not in _VENDOR_STOPWORDS]
    return list(dict.fromkeys(toks))  # dedupe, preserve order


def build_vendor_rule(transaction: Transaction) -> VendorRule:
    """Build a VendorRule for a single transaction."""
    tokens = _vendor_tokens(transaction.vendor)
    vendor_lower = transaction.vendor.lower().replace(".", " ").replace("-", " ")
    for key, aliases in _VENDOR_SENDER_ALIASES.items():
        key_normalized = key.replace(".", " ").replace("-", " ")
        if key_normalized in vendor_lower:
            tokens = list(dict.fromkeys(tokens + aliases))
    return VendorRule(vendor=transaction.vendor, sender_keywords=tokens)


def build_vendor_rules(transactions: list[Transaction]) -> list[VendorRule]:
    """Build a VendorRule for every transaction."""
    return [build_vendor_rule(tx) for tx in transactions]
