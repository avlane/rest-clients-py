import importlib
import os
import subprocess
import sys
import unittest

import restclients

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PublicApiTests(unittest.TestCase):
    def test_every_exported_name_resolves_to_the_object_in_its_module(self):
        for name, module in restclients._EXPORTS.items():
            with self.subTest(name=name):
                expected = getattr(importlib.import_module("restclients." + module), name)
                self.assertIs(getattr(restclients, name), expected)

    def test_all_matches_the_export_table(self):
        self.assertEqual(sorted(restclients.__all__), sorted(["__version__"] + list(restclients._EXPORTS)))

    def test_star_import_works(self):
        namespace = {}
        exec("from restclients import *", namespace)
        self.assertIn("UrllibClient", namespace)
        self.assertIn("NotFound", namespace)

    def test_unknown_names_raise_attribute_error(self):
        with self.assertRaises(AttributeError):
            restclients.DoesNotExist
        self.assertFalse(hasattr(restclients, "also_missing"))

    def test_dir_lists_the_lazy_names(self):
        self.assertIn("RetryPolicy", dir(restclients))

    def test_importing_the_package_is_cheap(self):
        code = ("import sys, restclients; "
                "heavy = [m for m in sys.modules if m.startswith('restclients.')]; "
                "print(','.join(heavy))")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "")
        code = "import restclients; restclients.UrllibClient; import sys; print('restclients.urllib_client' in sys.modules)"
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "True")

    def test_version_matches_pyproject(self):
        try:
            import tomllib
        except ModuleNotFoundError:
            self.skipTest("tomllib needs Python 3.11+")
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            self.assertEqual(tomllib.load(f)["project"]["version"], restclients.__version__)

    def test_a_first_look_at_the_api(self):
        from restclients import ApiError, NotFound, RetryPolicy, UrllibClient
        self.assertTrue(issubclass(NotFound, ApiError))
        client = UrllibClient(base_url="http://x", retry=RetryPolicy(max_attempts=2))
        self.assertEqual(client.retry.max_attempts, 2)


if __name__ == "__main__":
    unittest.main()
