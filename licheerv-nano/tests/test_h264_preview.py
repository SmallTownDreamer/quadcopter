"""Read-only local protocol tests; no camera or encoder started."""
import importlib.util
import json
import struct
import threading
import time
import unittest
import urllib.request
from pathlib import Path

spec = importlib.util.spec_from_file_location('preview', Path(__file__).parents[1] / 'scripts/h264_preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class IdleProcess:
    def poll(self):
        return None


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        preview.camera = preview.muxer = IdleProcess()
        preview.codec = 'avc1.424032'
        preview.initialization.extend(b'test-init')
        preview.sequence = 10
        preview.total_frames = 60
        preview.last_frame = time.monotonic()
        preview.history.extend([(preview.last_frame - .2, 6, 1000), (preview.last_frame, 6, 1000)])
        preview.segments.extend((i, f'segment-{i}'.encode()) for i in range(5, 11))
        cls.server = preview.ThreadingHTTPServer(('127.0.0.1', 0), preview.Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=3) as response:
            return response.headers, response.read()

    def test_initial_join_uses_latest_keyframe_fragment(self):
        headers, data = self.get('/segment.mp4?after=-1')
        self.assertEqual(headers['X-Segment-Id'], '10')
        self.assertEqual(data, b'segment-10')

    def test_lagging_client_skips_stale_fragments(self):
        headers, data = self.get('/segment.mp4?after=5')
        self.assertEqual(headers['X-Segment-Id'], '10')

    def test_near_live_client_keeps_continuity(self):
        headers, data = self.get('/segment.mp4?after=8')
        self.assertEqual(headers['X-Segment-Id'], '9')
        self.assertEqual(data, b'segment-9')

    def test_initialization_codec(self):
        headers, data = self.get('/init.mp4')
        self.assertEqual(headers['X-Video-Codec'], 'avc1.424032')
        self.assertEqual(data, b'test-init')

    def test_status_has_real_fragment_duration(self):
        _, data = self.get('/status')
        status = json.loads(data)
        self.assertTrue(status['healthy'])
        self.assertEqual(status['segment_ms'], 200)
        self.assertAlmostEqual(status['fps'], 30, places=1)
        self.assertEqual(status['target_buffer_ms'], 300)

    def test_fragment_frame_count(self):
        def box(kind, payload):
            return struct.pack('>I4s', len(payload) + 8, kind) + payload
        trun = box(b'trun', struct.pack('>II', 0, 6))
        moof = box(b'moof', box(b'traf', trun))
        self.assertEqual(preview.samples(moof), 6)


if __name__ == '__main__':
    unittest.main()
