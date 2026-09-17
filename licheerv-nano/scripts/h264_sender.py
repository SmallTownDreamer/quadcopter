#!/usr/bin/env python3
"""Board-side bounded raw H.264 TCP relay. No MP4 or HTTP work here."""
import argparse
import os
import selectors
import signal
import socket
import stat
import subprocess
import tempfile
import time
from pathlib import Path


class HeaderCache:
    """Cache tiny Annex-B SPS/PPS NALs; never retain a whole large frame."""
    def __init__(self):
        self.buf = bytearray()
        self.headers = {}

    def feed(self, data):
        self.buf.extend(data)
        while True:
            first = self.buf.find(b'\x00\x00\x01')
            if first < 0:
                self.buf[:] = self.buf[-3:]
                return
            if first:
                del self.buf[:first]
            second = self.buf.find(b'\x00\x00\x01', 3)
            if second < 0:
                if len(self.buf) > 4096:
                    self.buf[:] = self.buf[-3:]
                return
            kind = self.buf[3] & 31 if second > 3 else 0
            if kind in (7, 8) and second <= 4096:
                self.headers[kind] = bytes(self.buf[:second])
            del self.buf[:second]

    def prefix(self):
        return self.headers.get(7, b'') + self.headers.get(8, b'')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=9000)
    parser.add_argument('--adopt-fifo', type=Path)
    parser.add_argument('--adopt-pid', type=int)
    parser.add_argument('--start-paused', action='store_true')
    args = parser.parse_args()
    if bool(args.adopt_fifo) != bool(args.adopt_pid):
        parser.error('--adopt-fifo and --adopt-pid must be used together')
    if args.adopt_fifo:
        if not stat.S_ISFIFO(args.adopt_fifo.stat().st_mode):
            parser.error('Adopted source is not a FIFO')
        command = Path('/proc/{}/cmdline'.format(args.adopt_pid)).read_bytes().split(b'\0')[0]
        if command != b'/mnt/system/usr/bin/sample_venc':
            parser.error('Adopted PID is not the expected sample_venc executable')

    stopping = False
    active = not args.start_paused
    def stop(*_):
        nonlocal stopping
        stopping = True
    def activate(*_):
        nonlocal active
        active = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGUSR1, activate)
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.bind, args.port))
    listener.listen(2)
    listener.setblocking(False)
    selector = selectors.DefaultSelector()
    selector.register(listener, selectors.EVENT_READ, 'listener')
    camera = None
    temp = None
    keeper = None
    fifo_fd = None
    client = None
    pending = bytearray()
    headers = HeaderCache()
    pidfile = Path('/run/h264-sender.pid')
    ready = Path('/run/h264-sender.ready')
    max_queue = 256 * 1024

    def disconnect():
        nonlocal client
        if client is not None:
            selector.unregister(client)
            client.close()
            client = None
        pending.clear()

    try:
        if args.adopt_fifo:
            fifo = args.adopt_fifo
        else:
            temp = tempfile.TemporaryDirectory(prefix='h264-sender-', dir='/tmp')
            fifo = Path(temp.name) / 'test-0.h264'
            os.mkfifo(fifo, 0o600)
            keeper = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
        fifo_fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        if not args.adopt_fifo:
            command = ['/mnt/system/usr/bin/sample_venc', '--testMode=2', '--numChn=1',
                       '--bindmode=1', '--viWidth=2560', '--viHeight=1440', '-c', '264',
                       '-w', '2560', '-h', '1440', '--profile=0', '--h264EntropyMode=0',
                       '--rcMode=4', '--iqp=28', '--pqp=30', '--gop=6',
                       '--srcFramerate=30', '--framerate=30', '--isoSendFrmEn=0', '-n', '1000000000']
            with open('/tmp/h264-sender-encoder.log', 'wb') as log:
                camera = subprocess.Popen(command, cwd=temp.name, stdin=subprocess.DEVNULL,
                                          stdout=log, stderr=log, start_new_session=True)
        pidfile.write_text(str(os.getpid()))
        ready.write_text('pid={} source={} encoder={} paused={}\n'.format(
            os.getpid(), fifo, args.adopt_pid or camera.pid, not active))
        print('Raw H.264 relay listening on {}:{}; encoder {}; paused={}'.format(
            args.bind, args.port, args.adopt_pid or camera.pid, not active), flush=True)
        registered = False
        last_adopt_check = 0
        eof_since = None
        while not stopping:
            if active and not registered:
                selector.register(fifo_fd, selectors.EVENT_READ, 'fifo')
                registered = True
            if camera is not None and camera.poll() is not None:
                raise RuntimeError('Encoder exited with {}'.format(camera.returncode))
            if args.adopt_pid and time.monotonic() - last_adopt_check > 2:
                os.kill(args.adopt_pid, 0)
                last_adopt_check = time.monotonic()
            for key, mask in selector.select(timeout=.25):
                if key.data == 'listener':
                    connection, address = listener.accept()
                    if client is not None:
                        connection.close()
                        continue
                    connection.setblocking(False)
                    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
                    client = connection
                    pending.extend(headers.prefix())
                    selector.register(client, selectors.EVENT_READ | (selectors.EVENT_WRITE if pending else 0), 'client')
                    print('Receiver connected:', address, flush=True)
                elif key.data == 'fifo':
                    data = os.read(fifo_fd, 65536)
                    if not data:
                        eof_since = eof_since or time.monotonic()
                        if time.monotonic() - eof_since > 1:
                            raise RuntimeError('Encoder FIFO reached EOF')
                        time.sleep(.02)
                        continue
                    eof_since = None
                    headers.feed(data)
                    if client is not None:
                        if len(pending) + len(data) > max_queue:
                            print('Slow receiver disconnected: bounded queue full', flush=True)
                            disconnect()
                        else:
                            pending.extend(data)
                            selector.modify(client, selectors.EVENT_READ | selectors.EVENT_WRITE, 'client')
                    # No receiver: drain/discard to keep capture/encoding unblocked.
                elif key.data == 'client' and key.fileobj is client:
                    try:
                        if mask & selectors.EVENT_READ:
                            if not client.recv(1024):
                                disconnect()
                                continue
                        if client is not None and pending and mask & selectors.EVENT_WRITE:
                            sent = client.send(pending)
                            del pending[:sent]
                            if not pending:
                                selector.modify(client, selectors.EVENT_READ, 'client')
                    except BlockingIOError:
                        pass
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        disconnect()
    finally:
        disconnect()
        # Adopted encoders are deliberately NOT stopped: permits live rollback.
        if camera is not None and camera.poll() is None:
            camera.send_signal(signal.SIGINT)
            try:
                camera.wait(timeout=5)
            except subprocess.TimeoutExpired:
                camera.kill()
                camera.wait(timeout=3)
        selector.close()
        listener.close()
        if fifo_fd is not None:
            os.close(fifo_fd)
        if keeper is not None:
            os.close(keeper)
        pidfile.unlink(missing_ok=True)
        ready.unlink(missing_ok=True)
        if temp is not None:
            temp.cleanup()


if __name__ == '__main__':
    main()
