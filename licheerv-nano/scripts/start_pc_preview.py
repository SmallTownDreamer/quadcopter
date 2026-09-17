#!/usr/bin/env python3
"""Start a hidden local preview, or stop only the recognized preview server."""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', default='10.225.161.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--ffmpeg')
    parser.add_argument('--foreground', action='store_true')
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    url = 'http://127.0.0.1:{}/'.format(args.port)
    if args.stop:
        with urllib.request.urlopen(url + 'status', timeout=3) as response:
            status = json.load(response)
        if status.get('processing_host') != 'PC' or status.get('source_port') != 9000:
            raise SystemExit('Refusing to stop an unrecognized HTTP service')
        request = urllib.request.Request(url + 'stop', data=b'', method='POST')
        with urllib.request.urlopen(request, timeout=3) as response:
            print(response.read().decode())
        return
    # Do not accidentally start a second preview or disturb another HTTP service.
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', args.port))
        except OSError:
            raise SystemExit('Port {} already in use; check {}'.format(args.port, url))
    ffmpeg = args.ffmpeg or shutil.which('ffmpeg')
    if not ffmpeg or not Path(ffmpeg).is_file():
        raise SystemExit('Specify --ffmpeg with an existing FFmpeg executable')
    root = Path(__file__).resolve().parents[1]
    runtime = root / 'work/h264-pc'
    runtime.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-u', str(Path(__file__).with_name('h264_pc_preview.py')),
               '--board', args.board, '--port', str(args.port), '--ffmpeg', str(ffmpeg),
               '--runtime-dir', str(runtime)]
    if args.foreground:
        raise SystemExit(subprocess.call(command, cwd=root))
    with open(runtime / 'service.log', 'ab') as log:
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   creationflags=flags, start_new_session=os.name != 'nt')
    print('PC preview PID: {}; open {}'.format(process.pid, url))


if __name__ == '__main__':
    main()
