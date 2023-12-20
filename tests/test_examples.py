import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ExampleScriptTests(unittest.TestCase):
    def test_webhook_demo_runs_and_reports(self):
        result = subprocess.run([sys.executable, "-m", "examples.webhook_demo"], cwd=ROOT,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn("forged delivery refused: signature mismatch", lines)
        self.assertIn("stale delivery refused: timestamp outside the tolerance window", lines)
        self.assertEqual([l for l in lines if l.startswith("accepted:")], [
            "accepted: {'type': 'item.created', 'id': 1} id evt-1",
            "accepted: {'type': 'item.deleted', 'id': 1} id evt-2"])
        self.assertIn("duplicates dropped: 1", lines)


if __name__ == "__main__":
    unittest.main()
