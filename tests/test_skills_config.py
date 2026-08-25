import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle.skills.config import (
    SkillsConfigError,
    add_desired_kit,
    config_path,
    read_desired_kits,
    remove_desired_kit,
)


class TestReadDesiredKits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_means_no_kits_desired(self):
        self.assertEqual(read_desired_kits(self.root), [])

    def test_missing_skills_table_means_no_kits_desired(self):
        with open(config_path(self.root), "w") as f:
            f.write("[other]\nfoo = 1\n")
        self.assertEqual(read_desired_kits(self.root), [])

    def test_reads_kits_in_file_order(self):
        with open(config_path(self.root), "w") as f:
            f.write('[skills]\nkits = ["spec-kit", "software-engineering"]\n')
        self.assertEqual(read_desired_kits(self.root), ["spec-kit", "software-engineering"])

    def test_malformed_toml_raises(self):
        with open(config_path(self.root), "w") as f:
            f.write("this is not valid toml [[[")
        with self.assertRaises(SkillsConfigError):
            read_desired_kits(self.root)

    def test_skills_not_a_table_raises(self):
        with open(config_path(self.root), "w") as f:
            f.write("skills = 1\n")
        with self.assertRaises(SkillsConfigError):
            read_desired_kits(self.root)

    def test_kits_not_a_string_array_raises(self):
        with open(config_path(self.root), "w") as f:
            f.write("[skills]\nkits = [1, 2]\n")
        with self.assertRaises(SkillsConfigError):
            read_desired_kits(self.root)


class TestAddDesiredKit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_add_creates_minimal_file(self):
        changed = add_desired_kit(self.root, "software-engineering")
        self.assertTrue(changed)
        with open(config_path(self.root)) as f:
            content = f.read()
        self.assertEqual(content, '[skills]\nkits = ["software-engineering"]\n')
        self.assertEqual(read_desired_kits(self.root), ["software-engineering"])

    def test_second_add_preserves_first(self):
        add_desired_kit(self.root, "software-engineering")
        changed = add_desired_kit(self.root, "spec-kit")
        self.assertTrue(changed)
        self.assertEqual(read_desired_kits(self.root), ["software-engineering", "spec-kit"])

    def test_duplicate_add_does_not_duplicate_and_reports_no_change(self):
        add_desired_kit(self.root, "software-engineering")
        changed = add_desired_kit(self.root, "software-engineering")
        self.assertFalse(changed)
        self.assertEqual(read_desired_kits(self.root), ["software-engineering"])

    def test_add_preserves_unrelated_existing_content(self):
        with open(config_path(self.root), "w") as f:
            f.write(
                "# a comment above an unrelated table\n"
                "[other]\n"
                "foo = 1\n"
                "\n"
                "[skills]\n"
                'kits = ["software-engineering"]\n'
                "\n"
                "[after]\n"
                "bar = 2\n"
            )
        add_desired_kit(self.root, "spec-kit")
        with open(config_path(self.root)) as f:
            content = f.read()
        self.assertIn("# a comment above an unrelated table\n", content)
        self.assertIn("[other]\nfoo = 1\n", content)
        self.assertIn("[after]\nbar = 2\n", content)
        self.assertIn('kits = ["software-engineering", "spec-kit"]', content)

    def test_add_appends_skills_table_when_file_has_other_content_but_no_skills_table(self):
        with open(config_path(self.root), "w") as f:
            f.write("[other]\nfoo = 1\n")
        add_desired_kit(self.root, "spec-kit")
        with open(config_path(self.root)) as f:
            self.assertIn("[other]\nfoo = 1\n", f.read())
        self.assertEqual(read_desired_kits(self.root), ["spec-kit"])


class TestRemoveDesiredKit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_remove_on_empty_config_is_a_no_op(self):
        changed = remove_desired_kit(self.root, "software-engineering")
        self.assertFalse(changed)
        self.assertEqual(read_desired_kits(self.root), [])

    def test_remove_removes_only_the_named_kit(self):
        add_desired_kit(self.root, "software-engineering")
        add_desired_kit(self.root, "spec-kit")
        changed = remove_desired_kit(self.root, "software-engineering")
        self.assertTrue(changed)
        self.assertEqual(read_desired_kits(self.root), ["spec-kit"])

    def test_removing_last_kit_leaves_explicit_empty_list(self):
        add_desired_kit(self.root, "software-engineering")
        remove_desired_kit(self.root, "software-engineering")
        self.assertEqual(read_desired_kits(self.root), [])
        with open(config_path(self.root)) as f:
            content = f.read()
        self.assertIn("[skills]", content)
        self.assertIn("kits = []", content)

    def test_remove_is_idempotent(self):
        add_desired_kit(self.root, "software-engineering")
        remove_desired_kit(self.root, "software-engineering")
        changed = remove_desired_kit(self.root, "software-engineering")
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
