"""The exhaustive test: quote every combination of products in many quantities.

It starts the Go formatter 150 times. That is too slow to run on every push in a
real repository, so it stays out of the pre-push loop. The target is tagged manual: `bazel test //...` skips it,
and it runs when named (bazel test //services/quote:exhaustive_test) or through //:slow.
"""

import itertools
import unittest

from services.quote import quote

SKUS = ["WIDGET", "GADGET", "GIZMO", "SPROCKET"]


class ExhaustiveTest(unittest.TestCase):
    def test_every_combination_renders(self) -> None:
        for n in range(1, len(SKUS) + 1):
            for combo in itertools.combinations(SKUS, n):
                for qty in range(1, 11):
                    text = quote.render([f"{sku}={qty}" for sku in combo])
                    self.assertTrue(text.splitlines()[-1].startswith("total"), text)


if __name__ == "__main__":
    unittest.main()
