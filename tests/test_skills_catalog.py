import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle.skills.catalog import CATALOG, UnknownKitError, known_kit_ids, require_kit


class TestCatalog(unittest.TestCase):
    def test_known_kit_ids_matches_this_slice(self):
        self.assertEqual(known_kit_ids(), ["software-engineering", "spec-kit"])

    def test_require_kit_returns_matching_entry(self):
        info = require_kit("software-engineering")
        self.assertEqual(info.kit_id, "software-engineering")
        self.assertEqual(info.source, "t-step/skills")

    def test_require_kit_raises_and_lists_known_kits_for_an_unknown_id(self):
        with self.assertRaises(UnknownKitError) as ctx:
            require_kit("nonexistent-kit")
        self.assertIn("nonexistent-kit", str(ctx.exception))
        self.assertIn("software-engineering", str(ctx.exception))
        self.assertIn("spec-kit", str(ctx.exception))

    def test_every_catalog_entry_has_a_module_with_the_expected_functions(self):
        for kit_id, info in CATALOG.items():
            for fn_name in ("status", "add", "remove"):
                self.assertTrue(
                    callable(getattr(info.module, fn_name, None)),
                    f"{kit_id}'s module is missing a callable {fn_name}()",
                )


if __name__ == "__main__":
    unittest.main()
