import io
import os
import subprocess
import sys
import tempfile
import unittest

from restclients.openapi_gen import main

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "items-openapi.json")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), out, err)
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = os.path.join(self.tmp.name, "client.py")

    def test_prints_to_stdout(self):
        code, out, err = run(FIXTURE)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("class ItemsAPIClient(ApiClient):", out)

    def test_writes_a_file_that_imports(self):
        self.assertEqual(run(FIXTURE, "-o", self.output, "--class-name", "Shop")[0], 0)
        namespace = {"__name__": "shop_client"}
        with open(self.output, encoding="utf-8") as f:
            exec(compile(f.read(), self.output, "exec"), namespace)
        self.assertIn("Shop", namespace)

    def test_check_mode(self):
        self.assertEqual(run(FIXTURE, "-o", self.output, "--check")[0], 1)    # nothing written yet
        run(FIXTURE, "-o", self.output)
        self.assertEqual(run(FIXTURE, "-o", self.output, "--check"), (0, "", ""))
        with open(self.output, "a") as f:
            f.write("# hand edit\n")
        code, _, err = run(FIXTURE, "-o", self.output, "--check")
        self.assertEqual(code, 1)
        self.assertIn("out of date", err)

    def test_check_needs_output(self):
        self.assertEqual(run(FIXTURE, "--check")[0], 2)

    def test_bad_spec_is_a_clean_error(self):
        code, out, err = run("/no/such/spec.json")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("cannot read", err)

    def test_runs_as_a_module(self):
        result = subprocess.run([sys.executable, "-m", "restclients.openapi_gen", FIXTURE],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("def get_item(self, item_id):", result.stdout)


if __name__ == "__main__":
    unittest.main()
