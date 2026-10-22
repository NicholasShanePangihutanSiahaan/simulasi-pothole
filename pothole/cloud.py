"""A separate HTTP server and SQLite file represent the shared backend."""
import argparse
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .storage import Store
from .core import to_gps


def initialize_demo(store,cfg,seed):
    if seed and not store.get_meta('seed_initialized'):
        b=cfg['potholes'][1]
        lat,lon=to_gps(b['x'],b['y'],cfg['origin'])
        store.receive([{'event_id':'fixture-B-v1','latitude':lat,'longitude':lon,
                        'peak':6.0,'source':'contoh pengguna lain'}])
    store.set_meta('seed_initialized','1')


def validate_report(r):
    if not isinstance(r,dict) or not isinstance(r.get('event_id'),str) or not 1<=len(r['event_id'])<=100:
        raise ValueError('event_id tidak valid')
    for key,limit in [('latitude',90),('longitude',180),('peak',10000)]:
        value=r.get(key)
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or abs(value)>limit:
            raise ValueError(f'{key} tidak valid')
    if r['peak']<0:
        raise ValueError('peak harus positif')
    if r.get('source','imu')!='imu':
        raise ValueError('Hanya laporan pothole IMU yang boleh masuk database')


def handler(store, radius):
    class CloudHandler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def reply(self, value, status=200):
            data=json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path=='/api/potholes':
                self.reply({'potholes':store.hazards()})
            elif self.path=='/api/health':
                self.reply({'status':'ok','role':'server','hazards':len(store.hazards())})
            else:
                self.reply({'error':'not found'},404)

        def do_POST(self):
            if self.path not in ('/api/reports','/api/database/reset'):
                self.reply({'error':'not found'},404)
                return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=1000000:
                    raise ValueError('payload harus 1 byte sampai 1 MB')
                from urllib.parse import urlparse
                origin=self.headers.get('Origin')
                if origin and urlparse(origin).netloc!=self.headers.get('Host'):
                    raise ValueError('Origin tidak diizinkan')
                if self.headers.get_content_type()!='application/json':
                    raise ValueError('Gunakan application/json')
                data=json.loads(self.rfile.read(size))
                if self.path=='/api/database/reset':
                    if data.get('confirm')!='RESET POTHOLE DATABASE':
                        raise ValueError('Konfirmasi reset diperlukan')
                    # Serialize backup+clear with report uploads.
                    with store.lock:
                        backup=store.backup()
                        store.clear()
                    self.reply({'ok':True,'backup':backup})
                    return
                reports=data.get('reports')
                if not isinstance(reports,list) or len(reports)>100:
                    raise ValueError('maksimum 100 laporan per batch')
                for report in reports:
                    validate_report(report)
                self.reply({'accepted':store.receive(reports,radius)})
            except (ValueError,TypeError,AttributeError) as exc:
                self.reply({'error':str(exc)},400)
    return CloudHandler


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--data',default='data/server.sqlite3')
    parser.add_argument('--seed-demo',action='store_true')
    args=parser.parse_args()
    cfg=json.loads((Path(__file__).resolve().parents[1]/'config/demo.json').read_text())
    store=Store(args.data)
    # Explicit fixture, only on first initialization. A reset is durable.
    initialize_demo(store,cfg,args.seed_demo)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(store,cfg['sync']['merge_radius']))
    print(f'Server database: http://127.0.0.1:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
