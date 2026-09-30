"""A separate HTTP server and SQLite file represent the shared backend."""
import argparse
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .storage import Store
from .core import to_gps


def validate_report(r):
    if not isinstance(r,dict) or not isinstance(r.get('event_id'),str) or not 1<=len(r['event_id'])<=100:
        raise ValueError('event_id tidak valid')
    for key,limit in [('latitude',90),('longitude',180),('peak',10000)]:
        value=r.get(key)
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or abs(value)>limit:
            raise ValueError(f'{key} tidak valid')
    if r['peak']<0:
        raise ValueError('peak harus positif')


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
            if self.path!='/api/reports':
                self.reply({'error':'not found'},404)
                return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=1000000:
                    raise ValueError('payload harus 1 byte sampai 1 MB')
                reports=json.loads(self.rfile.read(size)).get('reports')
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
    if args.seed_demo:
        # Explicit demonstration fixture, only B. Detectors have no access to the map.
        b=cfg['potholes'][1]
        lat,lon=to_gps(b['x'],b['y'],cfg['origin'])
        store.receive([{'event_id':'fixture-B-v1','latitude':lat,'longitude':lon,'peak':6.0,'source':'contoh pengguna lain'}])
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
