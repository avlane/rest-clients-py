import unittest

from restclients import errors
from restclients.sse import SseEvent, follow_sse, iter_sse, parse_sse
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


def parse(text):
    return list(parse_sse(text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")))


class ParserTests(unittest.TestCase):
    def test_basic_event(self):
        self.assertEqual(parse("data: hello\n\n"), [SseEvent("message", "hello")])

    def test_multiline_data_and_event_type_and_id(self):
        events = parse("event: update\nid: 7\ndata: a\ndata: b\n\n")
        self.assertEqual(events, [SseEvent("update", "a\nb", "7")])

    def test_comments_and_unknown_fields_are_ignored(self):
        self.assertEqual(parse(": keep-alive\nfoo: bar\ndata: x\n\n"), [SseEvent("message", "x")])

    def test_only_one_leading_space_is_stripped(self):
        self.assertEqual(parse("data:  two spaces\n\n")[0].data, " two spaces")
        self.assertEqual(parse("data:nospace\n\n")[0].data, "nospace")

    def test_field_without_colon_has_empty_value(self):
        self.assertEqual(parse("data\n\n"), [SseEvent("message", "")])

    def test_event_without_data_is_not_dispatched(self):
        self.assertEqual(parse("event: ping\n\ndata: real\n\n"), [SseEvent("message", "real")])

    def test_id_persists_until_replaced_and_type_resets(self):
        events = parse("id: 1\nevent: a\ndata: x\n\ndata: y\n\nid: 2\ndata: z\n\n")
        self.assertEqual([(e.event, e.id) for e in events], [("a", "1"), ("message", "1"), ("message", "2")])

    def test_retry_must_be_digits(self):
        self.assertEqual(parse("retry: 1500\ndata: x\n\n")[0].retry, 1500)
        self.assertIsNone(parse("retry: soon\ndata: x\n\n")[0].retry)

    def test_retry_applies_even_when_its_event_has_no_data_and_sticks(self):
        events = parse("retry: 20\n\ndata: a\n\ndata: b\n\n")
        self.assertEqual([e.retry for e in events], [20, 20])

    def test_bom_is_ignored_and_bytes_are_accepted(self):
        self.assertEqual(list(parse_sse([b"\xef\xbb\xbfdata: x", b""])), [SseEvent("message", "x")])

    def test_unterminated_final_event_is_dropped(self):
        self.assertEqual(parse("data: partial"), [])


class StreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.client = UrllibClient(base_url=cls.server.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_events_over_a_chunked_response(self):
        events = list(iter_sse(self.client, "/events", {"count": 4}))
        self.assertEqual([e.id for e in events if e.event == "tick"], ["1", "2", "3", "4"])
        self.assertEqual(events[0].retry, 20)       # "retry: 20" arrived in an event without data
        self.assertEqual(events[0].data, '{"n": 1}')
        multi = [e for e in events if e.event == "message"][0]
        self.assertEqual(multi.data, "line one\nline two")

    def test_last_event_id_resumes(self):
        events = list(iter_sse(self.client, "/events", {"count": 5}, last_event_id=3))
        self.assertEqual([e.id for e in events if e.event == "tick"], ["4", "5"])
        self.assertEqual(self.server.requests[-1][2]["Last-Event-Id"], "3")

    def test_accept_header(self):
        list(iter_sse(self.client, "/events", {"count": 1}))
        self.assertEqual(self.server.requests[-1][2]["Accept"], "text/event-stream")

    def test_broken_stream_raises_after_delivering_what_arrived(self):
        seen = []
        with self.assertRaises(errors.TransportError):
            for event in iter_sse(self.client, "/events", {"count": 6, "drop_after": 2}):
                seen.append(event.id)
        self.assertEqual(seen, ["1", "2"])

    def test_follow_reconnects_with_last_event_id(self):
        sleeps = []
        events = list(follow_sse(self.client, "/events", {"count": 6, "drop_after": 2}, sleep=sleeps.append))
        ticks = [e.id for e in events if e.event == "tick"]
        self.assertEqual(ticks, ["1", "2", "3", "4", "5", "6"])      # no gaps, no repeats
        self.assertEqual(sleeps, [0.02])                              # the server's retry: 20
        resumed = [h for m, p, h in self.server.requests if p.startswith("/events") and "Last-Event-Id" in h]
        self.assertEqual(resumed[-1]["Last-Event-Id"], "2")

    def test_follow_gives_up_when_the_budget_is_spent(self):
        class AlwaysBroken(UrllibClient):
            def stream(self, *args, **kwargs):
                raise errors.TransportError("down")

        sleeps = []
        with self.assertRaises(errors.TransportError):
            list(follow_sse(AlwaysBroken(), "/events", max_reconnects=3, sleep=sleeps.append))
        self.assertEqual(sleeps, [1.0, 1.0, 1.0])

    def test_http_errors_are_not_retried(self):
        with self.assertRaises(errors.NotFound):
            list(follow_sse(self.client, "/no-such-stream", sleep=lambda s: None))


if __name__ == "__main__":
    unittest.main()
