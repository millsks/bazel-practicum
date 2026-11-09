"""The grader's view of //libs/pricing, from a second service package."""

import unittest

from libs.pricing import pricing


class PricingContractTest(unittest.TestCase):
    def test_catalog_is_generated_from_the_csv(self) -> None:
        order = pricing.parse_order(["SPROCKET=4", "GIZMO"])
        self.assertEqual(pricing.subtotal(order), 4 * 75 + 99999)

    def test_line_items_are_sorted_by_sku(self) -> None:
        names = [name for name, _, _, _ in pricing.line_items({"WIDGET": 1, "GADGET": 2})]
        self.assertEqual(names, ["Gadget", "Widget"])

    def test_tax_is_whole_cents(self) -> None:
        self.assertEqual(pricing.tax(3022, 20), 604)


if __name__ == "__main__":
    unittest.main()
