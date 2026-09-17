#!/usr/bin/env python3
"""PC-side raw H.264 receiver, copy-only MP4 remuxer and loopback browser UI."""
import argparse
import json
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import h264_preview as preview


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', default='10.225.161.1')
    parser.add_argument('--source-port', type=int, default=9000)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--ffmpeg', default=shutil.which('ffmpeg'))
    parser.add_argument('--runtime-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'work/h264-pc')
    args = parser.parse_args()
    if not args.ffmpeg or not Path(args.ffmpeg).is_file():
        parser.error('Pass --ffmpeg with the path to a working FFmpeg executable')
    args.runtime_dir.mkdir(parents=True, exist_ok=True)
    preview.PAGE = preview.PAGE.replace('板卡硬件编码'.encode(), '板卡硬件编码 · 电脑封装 / 网页服务'.encode())
    generation = 0
    process_lock = threading.Lock()

    class Handler(preview.Handler):
        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == '/status':
                with preview.condition:
                    history = list(preview.history)
                    elapsed = history[-1][0] - history[0][0] if len(history) > 1 else 0
                    fps = sum(x[1] for x in history[1:]) / elapsed if elapsed else 0
                    mbps = sum(x[2] for x in history[1:]) * 8 / elapsed / 1e6 if elapsed else 0
                    process = preview.muxer
                    data = dict(healthy=bool(preview.last_frame and time.monotonic() - preview.last_frame < 4),
                                frames=preview.total_frames, fps=round(fps, 2), mbps=round(mbps, 2),
                                codec=preview.codec, width=2560, height=1440, segments=preview.sequence,
                                muxer_exit=process.poll() if process else None,
                                muxer_pid=process.pid if process else None, generation=generation,
                                board=args.board, source_port=args.source_port, processing_host='PC',
                                gop=6, segment_ms=round(history[-1][1] / 30 * 1000, 1) if history else None,
                                target_buffer_ms=300, max_buffer_ms=700,
                                encoder_status='not directly polled; healthy indicates received video')
                try:
                    self.reply('application/json', json.dumps(data).encode())
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                return
            if url.path == '/segment.mp4':
                try:
                    after = int(parse_qs(url.query).get('after', ['-1'])[0])
                    with preview.condition:
                        restarted = after > preview.sequence
                    if restarted:
                        self.reply('text/plain', b'Stream restarted; reconnect player', 409)
                        return
                except ValueError:
                    pass
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return
            try:
                super().do_GET()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Normal when a Windows browser closes/reconnects a request.
                pass

        def do_POST(self):
            if self.path == '/stop':
                self.reply('text/plain', b'Stopping PC preview')
                preview.stopping.set()
            else:
                self.reply('text/plain', b'Not found', 404)

    server = preview.ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    server.timeout = .5
    pidfile = args.runtime_dir / 'preview.pid'
    pidfile.write_text(str(os.getpid()))
    signal.signal(signal.SIGINT, lambda *_: preview.stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: preview.stopping.set())

    def receive():
        nonlocal generation
        while not preview.stopping.is_set():
            with preview.condition:
                generation += 1
                preview.initialization.clear()
                preview.codec = None
                preview.segments.clear()
                preview.history.clear()
                preview.total_frames = preview.sequence = 0
                preview.last_frame = 0
                preview.condition.notify_all()
            command = [str(args.ffmpeg), '-nostdin', '-hide_banner', '-loglevel', 'warning',
                       '-rw_timeout', '5000000', '-fflags', '+genpts', '-f', 'h264', '-framerate', '30',
                       '-probesize', '262144', '-analyzeduration', '500000',
                       '-i', 'tcp://{}:{}?tcp_nodelay=1'.format(args.board, args.source_port),
                       '-c:v', 'copy', '-an', '-r', '30',
                       # Baseline has no B frames. Give raw packets explicit
                       # 30-fps PTS/DTS/duration; no decode or re-encode.
                       '-bsf:v', 'setts=time_base=1/90000:pts=N*3000:dts=N*3000:duration=3000',
                       '-video_track_timescale', '90000',
                       '-movflags', 'frag_keyframe+empty_moov+default_base_moof',
                       '-flush_packets', '1', '-f', 'mp4', 'pipe:1']
            try:
                with open(args.runtime_dir / 'muxer.log', 'ab') as log:
                    with process_lock:
                        if preview.stopping.is_set():
                            return
                        preview.muxer = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                        stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                print('Receiver generation {}: {}:{}'.format(generation, args.board, args.source_port), flush=True)
                preview.read_mp4()
                process = preview.muxer
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                process.stdout.close()
            except Exception as error:
                print('Receiver error:', error, flush=True)
            preview.stopping.wait(1)

    worker = threading.Thread(target=receive, daemon=True)
    worker.start()
    print('PC preview: http://127.0.0.1:{}/ ; source {}:{}'.format(args.port, args.board, args.source_port), flush=True)
    try:
        while not preview.stopping.is_set():
            server.handle_request()
    finally:
        preview.stopping.set()
        with preview.condition:
            preview.condition.notify_all()
        server.server_close()
        with process_lock:
            process = preview.muxer
            if process is not None and process.poll() is None:
                process.terminate()
        worker.join(timeout=5)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        pidfile.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
