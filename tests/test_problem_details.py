import unittest

from restclients import errors
from restclients.errors import ProblemDetails
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class ProblemDetailsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.client = UrllibClient(base_url=cls.server.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def error(self, path):
        with self.assertRaises(errors.ApiError) as ctx:
            self.client.get(path)
        return ctx.exception

    def test_rfc_9457_example(self):
        err = self.error("/problem/credit")
        problem = err.problem
        self.assertIsInstance(err, errors.Forbidden)
        self.assertEqual(problem.type, "https://example.com/probs/out-of-credit")
        self.assertEqual(problem.title, "You do not have enough credit.")
        self.assertEqual(problem.instance, "/account/12345/msgs/abc")
        self.assertEqual(problem.extensions, {"balance": 30, "accounts": ["/account/12345", "/account/67890"]})
        self.assertEqual(err.message, "Your current balance is 30, but that costs 50.")   # detail wins over title

    def test_recognised_without_the_content_type_when_type_and_title_are_present(self):
        self.assertEqual(self.error("/problem/plain-json").problem.title, "You do not have enough credit.")

    def test_defaults_for_a_minimal_problem(self):
        problem = self.error("/problem/minimal").problem
        self.assertEqual((problem.type, problem.status, problem.title), ("about:blank", 409, None))

    def test_extension_members_such_as_an_error_list(self):
        err = self.error("/problem/validation")
        self.assertEqual([e["pointer"] for e in err.problem.extensions["errors"]], ["#/age", "#/profile/color"])
        self.assertIn("must be a positive integer", err.message)

    def test_ordinary_error_bodies_are_not_problems(self):
        self.assertIsNone(self.error("/items/999").problem)               # {"error": "not found"}
        self.assertIsNone(self.error("/errors?shape=text").problem)
        self.assertIsNone(errors.ApiError("no body").problem)

    def test_content_type_check_is_case_insensitive_and_ignores_parameters(self):
        err = errors.error_for_status(400, body=b'{"status": 400}',
                                      headers={"content-type": "Application/Problem+JSON; charset=utf-8"})
        self.assertIsInstance(err.problem, ProblemDetails)

    def test_repr(self):
        self.assertIn("out-of-credit", repr(self.error("/problem/credit").problem))


if __name__ == "__main__":
    unittest.main()
