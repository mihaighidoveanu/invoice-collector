"""Phase 2 — Rule builder.

Fully deterministic: builds Gmail search rules from transactions.
No LLM calls.
"""

from models import SearchRule, Transaction

_INVOICE_SUBJECT_KEYWORDS = ["invoice", "receipt", "factura", "bill"]
_INVOICE_FILENAME_KEYWORDS = ["invoice", "receipt", "factura"]


def _vendor_tokens(vendor: str) -> list[str]:
    """Split vendor name into lowercase tokens, deduplicated, preserving order."""
    seen: set[str] = set()
    tokens: list[str] = []
    for token in vendor.lower().split():
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def build_rule(transaction: Transaction) -> SearchRule:
    """Build a SearchRule for a single transaction."""
    tokens = _vendor_tokens(transaction.vendor)
    amount_str = f"{transaction.amount:.2f}"

    subject_keywords = tokens + _INVOICE_SUBJECT_KEYWORDS
    body_keywords = [amount_str] + tokens
    attachment_filename_keywords = tokens + _INVOICE_FILENAME_KEYWORDS

    return SearchRule(
        vendor=transaction.vendor,
        subject_keywords=subject_keywords,
        body_keywords=body_keywords,
        attachment_filename_keywords=attachment_filename_keywords,
    )


def build_rules(transactions: list[Transaction]) -> list[SearchRule]:
    """Build a SearchRule for every transaction."""
    return [build_rule(tx) for tx in transactions]
