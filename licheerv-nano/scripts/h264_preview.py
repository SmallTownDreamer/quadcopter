#!/usr/bin/env python3
"""LicheeRV Nano: hardware H.264 -> fragmented MP4 -> browser MediaSource."""
import collections
import json
import os
import signal
import struct
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LicheeRV Nano H.264 视频</title><style>
body{margin:0;background:#111820;color:#e7eef7;font:16px system-ui;padding:24px}
main{max-width:1280px;margin:auto}h1{font-size:23px}video{width:100%;background:#000;border-radius:12px;aspect-ratio:16/9}
p{color:#a4b6c9}button{padding:9px 16px;border:0;border-radius:8px;background:#30475e;color:white;cursor:pointer}
</style><main><h1>LicheeRV Nano · H.264 实时视频</h1>
<p>2560 × 1440 · 板卡硬件编码 · 200 ms 视频分片 · 低延时预览 · 无音频</p>
<video id="video" controls autoplay muted playsinline></video>
<p id="status">正在连接…</p><p id="playback"></p><button id="reconnect">重新连接</button>
<script>
const video=document.getElementById('video'),status=document.getElementById('status'),playback=document.getElementById('playback');
let controller=null,objectURL=null;
const TARGET_BUFFER=0.30,MAX_BUFFER=0.70;
window.previewMetrics={segments:0,skippedSegments:0,seeks:0,lastSequence:-1};
function append(sb,bytes){return new Promise((resolve,reject)=>{const done=()=>{clean();resolve()},fail=()=>{clean();reject(new Error('视频分片解码失败'))};function clean(){sb.removeEventListener('updateend',done);sb.removeEventListener('error',fail)}sb.addEventListener('updateend',done,{once:true});sb.addEventListener('error',fail,{once:true});try{sb.appendBuffer(bytes)}catch(e){clean();reject(e)}})}
async function connect(){
 if(controller)controller.abort();controller=new AbortController();const signal=controller.signal;
 if(objectURL)URL.revokeObjectURL(objectURL);video.removeAttribute('src');video.load();
 video.playbackRate=1;window.previewMetrics={segments:0,skippedSegments:0,seeks:0,lastSequence:-1};
 try{
  playback.textContent='等待视频初始化…';
  const initResponse=await fetch('/init.mp4',{signal,cache:'no-store'});if(!initResponse.ok)throw new Error('编码器尚未就绪');
  const mime='video/mp4; codecs="'+initResponse.headers.get('X-Video-Codec')+'"';
  if(!window.MediaSource||!MediaSource.isTypeSupported(mime))throw new Error('此浏览器不支持 '+mime+'，请使用新版 Edge / Chrome');
  const init=await initResponse.arrayBuffer(),ms=new MediaSource();objectURL=URL.createObjectURL(ms);video.src=objectURL;
  await new Promise(resolve=>ms.addEventListener('sourceopen',resolve,{once:true}));if(signal.aborted)return;
  const sb=ms.addSourceBuffer(mime);sb.mode='sequence';await append(sb,init);
  let seq=-1;video.onloadedmetadata=()=>video.play().catch(()=>{});
  while(!signal.aborted){
   const response=await fetch('/segment.mp4?after='+seq,{signal,cache:'no-store'});
   if(response.status===204)continue;if(!response.ok)throw new Error('视频流中断');
   const nextSeq=Number(response.headers.get('X-Segment-Id'));
   if(seq>=0)window.previewMetrics.skippedSegments+=Math.max(0,nextSeq-seq-1);
   seq=nextSeq;window.previewMetrics.lastSequence=seq;window.previewMetrics.segments++;
   await append(sb,await response.arrayBuffer());
   if(video.buffered.length){let end=video.buffered.end(video.buffered.length-1),start=video.buffered.start(0);
    const ahead=end-video.currentTime;
    if(video.currentTime<start||ahead>MAX_BUFFER){video.currentTime=Math.max(start,end-TARGET_BUFFER);window.previewMetrics.seeks++;video.playbackRate=1}
    else video.playbackRate=ahead>TARGET_BUFFER+0.10?1.04:1;
    if(sb.buffered.length&&video.currentTime>15){await new Promise(resolve=>{sb.addEventListener('updateend',resolve,{once:true});sb.remove(0,video.currentTime-10)})}
   }
   if(video.paused)video.play().catch(()=>{});
  }
 }catch(e){if(!signal.aborted){playback.textContent=e.message;setTimeout(()=>{if(!signal.aborted)connect()},3000)}}
}
document.getElementById('reconnect').onclick=connect;
async function stats(){try{const s=await(await fetch('/status',{cache:'no-store'})).json();status.textContent=(s.healthy?'● 编码正常':'等待 / 编码中断')+' · '+s.fps.toFixed(1)+' 帧/秒 · '+s.mbps.toFixed(2)+' Mbps · 已编码 '+s.frames+' 帧';if(video.videoWidth){const q=video.getVideoPlaybackQuality?.(),ahead=video.buffered.length?Math.max(0,video.buffered.end(video.buffered.length-1)-video.currentTime):0;playback.textContent='浏览器：'+video.videoWidth+' × '+video.videoHeight+' · 已显示 '+(q?.totalVideoFrames??'?')+' 帧 · 丢帧 '+(q?.droppedVideoFrames??'?')+' · 播放缓冲 '+Math.round(ahead*1000)+' ms（非端到端延迟） · 跳过旧分片 '+window.previewMetrics.skippedSegments}}catch(e){status.textContent='连接中断'}setTimeout(stats,2000)}
connect();stats();
</script></main></html>'''.encode()

condition = threading.Condition()
stopping = threading.Event()
segments = collections.deque(maxlen=6)
history = collections.deque(maxlen=60)
initialization = bytearray()
codec = None
total_frames = 0
sequence = 0
last_frame = 0.0
camera = muxer = None


def samples(data):
    count = 0
    offset = 0
    while offset + 8 <= len(data):
        size, kind = struct.unpack_from('>I4s', data, offset)
        if size < 8 or offset + size > len(data):
            break
        payload = data[offset + 8:offset + size]
        if kind in (b'moof', b'traf'):
            count += samples(payload)
        elif kind == b'trun' and len(payload) >= 8:
            count += struct.unpack_from('>I', payload, 4)[0]
        offset += size
    return count


def read_mp4():
    global codec, total_frames, sequence, last_frame
    buf = bytearray()
    fragment = bytearray()
    try:
        while not stopping.is_set():
            chunk = os.read(muxer.stdout.fileno(), 65536)
            if not chunk:
                return
            buf.extend(chunk)
            while len(buf) >= 8:
                size, kind = struct.unpack_from('>I4s', buf)
                if size == 1:
                    if len(buf) < 16:
                        break
                    size = struct.unpack_from('>Q', buf, 8)[0]
                if size < 8 or size > 16 * 1024 * 1024:
                    raise RuntimeError('Invalid MP4 box size')
                if len(buf) < size:
                    break
                box = bytes(buf[:size])
                del buf[:size]
                if kind in (b'ftyp', b'moov'):
                    with condition:
                        initialization.extend(box)
                        if kind == b'moov':
                            index = box.find(b'avcC')
                            if index < 0:
                                raise RuntimeError('H.264 configuration missing')
                            codec = 'avc1.' + box[index + 5:index + 8].hex()
                            condition.notify_all()
                elif kind == b'moof':
                    fragment = bytearray(box)
                elif kind == b'mdat' and fragment:
                    fragment.extend(box)
                    data = bytes(fragment)
                    n = samples(data)
                    with condition:
                        sequence += 1
                        total_frames += n
                        last_frame = time.monotonic()
                        segments.append((sequence, data))
                        history.append((last_frame, n, len(data)))
                        condition.notify_all()
                    fragment.clear()
    except Exception as error:
        print('MP4 reader error:', error, flush=True)
        stopping.set()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, content_type, data=b'', code=200, headers=None):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        try:
            if url.path == '/':
                self.reply('text/html; charset=utf-8', PAGE)
            elif url.path == '/status':
                with condition:
                    elapsed = history[-1][0] - history[0][0] if len(history) > 1 else 0
                    fps = sum(x[1] for x in list(history)[1:]) / elapsed if elapsed else 0
                    mbps = sum(x[2] for x in list(history)[1:]) * 8 / elapsed / 1e6 if elapsed else 0
                    data = dict(healthy=bool(last_frame and time.monotonic() - last_frame < 4),
                                frames=total_frames, fps=round(fps, 2), mbps=round(mbps, 2),
                                codec=codec, width=2560, height=1440, segments=sequence,
                                camera_exit=camera.poll(), muxer_exit=muxer.poll(),
                                gop=6, segment_ms=round(history[-1][1] / 30 * 1000, 1) if history else None,
                                segment_age_ms=round((time.monotonic() - last_frame) * 1000, 1) if last_frame else None,
                                target_buffer_ms=300, max_buffer_ms=700)
                self.reply('application/json', json.dumps(data).encode())
            elif url.path == '/init.mp4':
                with condition:
                    condition.wait_for(lambda: codec is not None or stopping.is_set(), timeout=12)
                    data, mime_codec = bytes(initialization), codec
                if mime_codec:
                    self.reply('video/mp4', data, headers={'X-Video-Codec': mime_codec})
                else:
                    self.reply('text/plain', b'Encoder not ready', 503)
            elif url.path == '/segment.mp4':
                after = int(parse_qs(url.query).get('after', ['-1'])[0])
                with condition:
                    condition.wait_for(lambda: (bool(segments) and sequence > after) or stopping.is_set(), timeout=8)
                    item = None
                    if segments:
                        # Every fragment starts with an IDR. Skip old fragments
                        # when a slow viewer falls >2 GOPs behind live output.
                        item = segments[-1] if after < 0 or sequence - after > 2 else next((x for x in segments if x[0] > after), None)
                if item:
                    self.reply('video/mp4', item[1], headers={'X-Segment-Id': item[0]})
                else:
                    self.reply('video/mp4', code=204)
            else:
                self.reply('text/plain', b'Not found', 404)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except ValueError:
            self.reply('text/plain', b'Invalid sequence', 400)


def finish(process):
    if process is not None and process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def main():
    global camera, muxer
    server = ThreadingHTTPServer(('0.0.0.0', 8080), Handler)
    server.daemon_threads = True
    server.timeout = 0.5
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    pidfile = Path('/run/h264-preview.pid')
    pidfile.write_text(str(os.getpid()))
    with tempfile.TemporaryDirectory(prefix='h264-preview-', dir='/tmp') as temp:
        fifo = Path(temp) / 'test-0.h264'
        os.mkfifo(fifo, 0o600)
        keeper = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
        try:
            command = ['/usr/bin/ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'warning',
                       '-fflags', '+genpts', '-f', 'h264', '-framerate', '30',
                       '-probesize', '262144', '-analyzeduration', '1000000', '-i', str(fifo),
                       '-c:v', 'copy', '-an', '-movflags', 'frag_keyframe+empty_moov+default_base_moof',
                       '-flush_packets', '1', '-f', 'mp4', 'pipe:1']
            with open('/tmp/h264-preview-muxer.log', 'wb') as log:
                muxer = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=log, start_new_session=True)
            threading.Thread(target=read_mp4, daemon=True).start()
            command = ['/mnt/system/usr/bin/sample_venc', '--testMode=2', '--numChn=1',
                       '--bindmode=1', '--viWidth=2560', '--viHeight=1440', '-c', '264',
                       '-w', '2560', '-h', '1440', '--profile=0', '--h264EntropyMode=0',
                       '--rcMode=4', '--iqp=28', '--pqp=30', '--gop=6',
                       '--srcFramerate=30', '--framerate=30', '--isoSendFrmEn=0', '-n', '1000000000']
            with open('/tmp/h264-preview-encoder.log', 'wb') as log:
                camera = subprocess.Popen(command, cwd=temp, stdin=subprocess.DEVNULL,
                                          stdout=log, stderr=log, start_new_session=True)
            print('Hardware H.264 browser preview listening on port 8080', flush=True)
            while not stopping.is_set():
                server.handle_request()
                if camera.poll() is not None or muxer.poll() is not None:
                    raise RuntimeError('Video pipeline exited; see /tmp/h264-preview-*.log')
        finally:
            stopping.set()
            with condition:
                condition.notify_all()
            server.server_close()
            finish(camera)
            finish(muxer)
            if muxer is not None:
                muxer.stdout.close()
            os.close(keeper)
            pidfile.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
