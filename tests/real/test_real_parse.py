"""Real-data tests for parse_statement().

After a first run, fill in the EXPECTED_* values below and remove the skip guards.
"""

import pytest

from models import Transaction

# ---------------------------------------------------------------------------
# Update after first run against your test statement PDF
# ---------------------------------------------------------------------------
EXPECTED_TRANSACTION_COUNT = None   # e.g. 12
EXPECTED_VENDORS = set()            # e.g. {"AWS", "DigitalOcean", "Stripe"}
# ---------------------------------------------------------------------------


def test_parse_returns_transactions(real_transactions):
    assert len(real_transactions) > 0


def test_parse_all_have_required_fields(real_transactions):
    for tx in real_transactions:
        assert isinstance(tx, Transaction)
        assert tx.vendor
        assert tx.amount > 0
        assert tx.date
        assert tx.raw_description


def test_parse_transaction_count(real_transactions):
    if EXPECTED_TRANSACTION_COUNT is None:
        pytest.skip("EXPECTED_TRANSACTION_COUNT not set")
    assert len(real_transactions) == EXPECTED_TRANSACTION_COUNT


def test_parse_expected_vendors_present(real_transactions):
    if not EXPECTED_VENDORS:
        pytest.skip("EXPECTED_VENDORS not set")
    found = {tx.vendor for tx in real_transactions}
    missing = EXPECTED_VENDORS - found
    assert not missing, f"Expected vendors not found: {missing}"
