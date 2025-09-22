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


class ServeScriptTests(unittest.TestCase):
    def test_serve_starts_answers_and_stops_on_sigint(self):
        import json
        import signal
        import urllib.request

        proc = subprocess.Popen([sys.executable, "-u", "-m", "examples.serve"], cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            line = proc.stdout.readline().strip()
            self.assertTrue(line.startswith("listening on http://127.0.0.1:"), line)
            url = line.split("listening on ", 1)[1]
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # no proxy for loopback
            with opener.open(url + "/", timeout=10) as resp:
                routes = json.load(resp)["routes"]
            self.assertIn("/flaky", routes)
            self.assertIn("/oauth", routes)
            self.assertNotIn("/root", routes)
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            proc.stderr.close()
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
