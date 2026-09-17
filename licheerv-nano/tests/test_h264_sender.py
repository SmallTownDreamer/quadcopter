import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('sender', Path(__file__).parents[1] / 'scripts/h264_sender.py')
sender = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sender)


class HeaderTests(unittest.TestCase):
    def test_chunk_boundaries(self):
        cache = sender.HeaderCache()
        sps = b'\0\0\1\x67sps-data'
        pps = b'\0\0\1\x68pps-data'
        stream = sps + pps + b'\0\0\1\x65iframe'
        for byte in stream:
            cache.feed(bytes([byte]))
        self.assertEqual(cache.prefix(), sps + pps)

    def test_large_frames_do_not_accumulate(self):
        cache = sender.HeaderCache()
        cache.feed(b'\0\0\1\x65' + b'x' * 100000)
        self.assertLessEqual(len(cache.buf), 4096)
        cache.feed(b'\0\0\1\x67new-sps\0\0\1\x68new-pps\0\0\1\x65frame')
        self.assertIn(b'new-sps', cache.prefix())
        self.assertIn(b'new-pps', cache.prefix())


if __name__ == '__main__':
    unittest.main()
