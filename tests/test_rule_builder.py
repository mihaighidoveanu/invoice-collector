"""Tests for agent/rule_builder.py — fully deterministic, no external calls."""

from datetime import date

import pytest

from agent.rule_builder import _vendor_tokens, build_rule, build_rules
from models import SearchRule, Transaction

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_tx(vendor: str, amount: float = 29.99, currency: str = "USD") -> Transaction:
    return Transaction(
        vendor=vendor,
        amount=amount,
        currency=currency,
        date=date(2025, 3, 5),
        raw_description=f"RAW {vendor.upper()}",
    )


# ---------------------------------------------------------------------------
# _vendor_tokens
# ---------------------------------------------------------------------------


def test_vendor_tokens_single_word():
    assert _vendor_tokens("Amazon") == ["amazon"]


def test_vendor_tokens_multi_word():
    assert _vendor_tokens("Google Cloud") == ["google", "cloud"]


def test_vendor_tokens_deduplication():
    tokens = _vendor_tokens("Square Square")
    assert tokens == ["square"]


def test_vendor_tokens_lowercased():
    tokens = _vendor_tokens("Netflix")
    assert all(t == t.lower() for t in tokens)


# ---------------------------------------------------------------------------
# build_rule
# ---------------------------------------------------------------------------


def test_build_rule_returns_search_rule():
    rule = build_rule(make_tx("Amazon"))
    assert isinstance(rule, SearchRule)


def test_build_rule_vendor_matches():
    rule = build_rule(make_tx("Amazon"))
    assert rule.vendor == "Amazon"


def test_build_rule_subject_keywords_include_vendor_and_invoice_terms():
    rule = build_rule(make_tx("Google Cloud"))
    assert "google" in rule.subject_keywords
    assert "cloud" in rule.subject_keywords
    assert "invoice" in rule.subject_keywords
    assert "receipt" in rule.subject_keywords
    assert "factura" in rule.subject_keywords
    assert "bill" in rule.subject_keywords


def test_build_rule_body_keywords_include_amount_and_vendor():
    rule = build_rule(make_tx("Netflix", amount=15.99))
    assert "15.99" in rule.body_keywords
    assert "netflix" in rule.body_keywords


def test_build_rule_attachment_keywords_include_vendor_and_invoice_terms():
    rule = build_rule(make_tx("Dropbox"))
    assert "dropbox" in rule.attachment_filename_keywords
    assert "invoice" in rule.attachment_filename_keywords
    assert "receipt" in rule.attachment_filename_keywords
    assert "factura" in rule.attachment_filename_keywords


def test_build_rule_amount_formatted_two_decimal_places():
    rule = build_rule(make_tx("Zoom", amount=100.0))
    assert "100.00" in rule.body_keywords


# ---------------------------------------------------------------------------
# build_rules
# ---------------------------------------------------------------------------


def test_build_rules_empty_input():
    assert build_rules([]) == []


def test_build_rules_length_matches_transactions():
    txs = [make_tx("Amazon"), make_tx("Google Cloud"), make_tx("Netflix")]
    rules = build_rules(txs)
    assert len(rules) == 3


def test_build_rules_vendors_preserved():
    txs = [make_tx("Amazon"), make_tx("Dropbox")]
    rules = build_rules(txs)
    assert rules[0].vendor == "Amazon"
    assert rules[1].vendor == "Dropbox"


@pytest.mark.parametrize(
    "vendor,amount",
    [
        ("Zoom", 14.99),
        ("Slack", 7.25),
        ("GitHub", 4.00),
        ("Figma", 45.00),
        ("Notion", 16.00),
    ],
)
def test_build_rule_parametrized(vendor: str, amount: float):
    rule = build_rule(make_tx(vendor, amount=amount))
    assert rule.vendor == vendor
    assert f"{amount:.2f}" in rule.body_keywords
    assert vendor.lower() in rule.subject_keywords
