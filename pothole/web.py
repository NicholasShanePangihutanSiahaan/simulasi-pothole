import argparse
import csv
import io
import json
import mimetypes
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .runtime import Runtime

STATIC=Path(__file__).resolve().parents[1]/'web'


def handler(runtime):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def reply(self,data,mime='application/json',status=200):
            if not isinstance(data,bytes):
                data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):
                pass

        def do_GET(self):
            path=urlparse(self.path).path
            if path=='/api/state':
                self.reply(runtime.state())
            elif path=='/api/export.csv':
                out=io.StringIO()
                rows=runtime.store.cached()
                keys=['id','latitude','longitude','observations','peak','source','updated_at']
                writer=csv.DictWriter(out,fieldnames=keys,extrasaction='ignore')
                writer.writeheader()
                writer.writerows(rows)
                self.reply(out.getvalue().encode(),'text/csv; charset=utf-8')
            elif path in ('/stream/camera','/stream/chase'):
                kind=path.rsplit('/',1)[1]
                self.send_response(200)
                self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame')
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                seq=-1
                try:
                    while not runtime.stop.wait(.03):
                        with runtime.lock:
                            data=runtime.frames[kind]
                            new_seq=runtime.frame_seq[kind]
                        if data and new_seq!=seq:
                            self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n')
                            self.wfile.flush()
                            seq=new_seq
                except (BrokenPipeError,ConnectionResetError,TimeoutError):
                    pass
            elif path in ('/snapshot/camera.jpg','/snapshot/chase.jpg'):
                kind=path.split('/')[-1].split('.')[0]
                with runtime.lock:
                    frame=runtime.frames[kind]
                self.reply(frame if frame else {'error':'menunggu kamera'},'image/jpeg' if frame else 'application/json',200 if frame else 503)
            elif path in ('/','/app.js','/style.css'):
                file=STATIC/('index.html' if path=='/' else path[1:])
                self.reply(file.read_bytes(),mimetypes.guess_type(file)[0] or 'text/plain')
            else:
                self.reply({'error':'not found'},status=404)

        def do_POST(self):
            # Reject cross-origin writes to the local bicycle controls.
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'):
                self.reply({'error':'origin tidak diizinkan'},status=403)
                return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<8192:
                    raise ValueError('payload tidak valid')
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict):
                    raise ValueError('objek JSON diperlukan')
                if self.path=='/api/control':
                    runtime.set_control(data)
                elif self.path=='/api/options':
                    runtime.set_options(data)
                elif self.path=='/api/reset':
                    runtime.reset(data.get('scenario','start'))
                elif self.path=='/api/heartbeat':
                    with runtime.lock:
                        runtime.last_client=time.monotonic()
                else:
                    self.reply({'error':'not found'},status=404)
                    return
                self.reply({'ok':True})
            except (ValueError,TypeError,KeyError) as exc:
                self.reply({'error':str(exc)},status=400)
    return Handler


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data',default='data/device.sqlite3')
    parser.add_argument('--server',default='http://127.0.0.1:8766')
    args=parser.parse_args()
    runtime=Runtime(args.data,args.server)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(runtime))
    print(f'Dashboard: http://localhost:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
        server.server_close()


if __name__=='__main__':
    main()
