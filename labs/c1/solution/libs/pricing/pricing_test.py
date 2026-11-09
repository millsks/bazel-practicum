"""Unit tests for libs/pricing, run with pytest."""

import pytest

from libs.pricing import pricing


def test_parse_order_adds_up_repeated_skus() -> None:
    assert pricing.parse_order(["widget=2", "GADGET", "WIDGET=1"]) == {"WIDGET": 3, "GADGET": 1}


def test_parse_order_rejects_unknown_skus() -> None:
    with pytest.raises(ValueError, match="unknown SKU 'DOOHICKEY'"):
        pricing.parse_order(["DOOHICKEY=1"])


def test_subtotal_uses_the_generated_catalog() -> None:
    assert pricing.subtotal({"WIDGET": 2, "GADGET": 1}) == 2 * 499 + 1250


def test_tax_rounds_half_up() -> None:
    assert pricing.tax(2248, 8) == 180  # 179.84
    assert pricing.tax(50, 1) == 1  # 0.5 rounds up
    assert pricing.tax(49, 1) == 0


def test_table_aligns_numbers_right() -> None:
    text = pricing.table([("Widget", "2", "$4.99", "$9.98")])
    assert text.splitlines()[-1] == "Widget      2   $4.99    $9.98"
