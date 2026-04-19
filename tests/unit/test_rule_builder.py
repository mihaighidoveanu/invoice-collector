"""Tests for agent/rule_builder.py — fully deterministic, no external calls."""

from datetime import date

import pytest

from agent.rule_builder import INVOICE_INDICATOR_KEYWORDS, _vendor_tokens, build_vendor_rule, build_vendor_rules
from models import Transaction, VendorRule


def make_tx(vendor: str, amount: float = 29.99) -> Transaction:
    return Transaction(
        vendor=vendor,
        amount=amount,
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


def test_vendor_tokens_filters_short_tokens():
    tokens = _vendor_tokens("AB Google")
    assert "ab" not in tokens
    assert "google" in tokens


def test_vendor_tokens_filters_stopwords():
    tokens = _vendor_tokens("Acme SRL")
    assert "srl" not in tokens
    assert "acme" in tokens


def test_vendor_tokens_filters_multiple_stopwords():
    for stopword in ["sa", "ltd", "inc", "sc", "srls"]:
        tokens = _vendor_tokens(f"Vendor {stopword.upper()}")
        assert stopword not in tokens


# ---------------------------------------------------------------------------
# build_vendor_rule
# ---------------------------------------------------------------------------


def test_build_vendor_rule_returns_vendor_rule():
    rule = build_vendor_rule(make_tx("Amazon"))
    assert isinstance(rule, VendorRule)


def test_build_vendor_rule_vendor_matches():
    rule = build_vendor_rule(make_tx("Amazon"))
    assert rule.vendor == "Amazon"


def test_build_vendor_rule_sender_keywords_include_vendor_tokens():
    rule = build_vendor_rule(make_tx("Google Cloud"))
    assert "google" in rule.sender_keywords
    assert "cloud" in rule.sender_keywords


def test_build_vendor_rule_stopwords_excluded_from_sender_keywords():
    rule = build_vendor_rule(make_tx("Acme SRL"))
    assert "srl" not in rule.sender_keywords
    assert "acme" in rule.sender_keywords


# ---------------------------------------------------------------------------
# INVOICE_INDICATOR_KEYWORDS
# ---------------------------------------------------------------------------


def test_invoice_indicator_keywords_present():
    for kw in ["invoice", "factura", "receipt", "bill", "payment"]:
        assert kw in INVOICE_INDICATOR_KEYWORDS


# ---------------------------------------------------------------------------
# build_vendor_rules
# ---------------------------------------------------------------------------


def test_build_vendor_rules_empty_input():
    assert build_vendor_rules([]) == []


def test_build_vendor_rules_length_matches_transactions():
    txs = [make_tx("Amazon"), make_tx("Google Cloud"), make_tx("Netflix")]
    rules = build_vendor_rules(txs)
    assert len(rules) == 3


def test_build_vendor_rules_vendors_preserved():
    txs = [make_tx("Amazon"), make_tx("Dropbox")]
    rules = build_vendor_rules(txs)
    assert rules[0].vendor == "Amazon"
    assert rules[1].vendor == "Dropbox"


@pytest.mark.parametrize(
    "vendor",
    ["Zoom", "Slack", "GitHub", "Figma", "Notion"],
)
def test_build_vendor_rule_parametrized(vendor: str):
    rule = build_vendor_rule(make_tx(vendor))
    assert rule.vendor == vendor
    assert vendor.lower() in rule.sender_keywords
