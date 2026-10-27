import unittest
from framing import JsonLines, encode_message, MAX_LINE


class JsonLinesTests(unittest.TestCase):
    def test_fragmented_json(self):
        p = JsonLines()
        self.assertEqual(p.feed(b'{"action":"pi'), [])
        self.assertEqual(p.feed(b'ng"}\n'), [{'action': 'ping'}])

    def test_multiple_messages(self):
        p = JsonLines()
        self.assertEqual(p.feed(b'{"a":1}\n{"b":2}\n'), [{'a': 1}, {'b': 2}])

    def test_reject_list(self):
        with self.assertRaises(ValueError):
            JsonLines().feed(b'[1,2]\n')

    def test_reject_large_line(self):
        with self.assertRaises(ValueError):
            JsonLines().feed(b'a'*(MAX_LINE+1))

    def test_encode_utf8(self):
        self.assertEqual(JsonLines().feed(encode_message({'text': 'Grüße'})),
                         [{'text': 'Grüße'}])


if __name__ == '__main__':
    unittest.main()
