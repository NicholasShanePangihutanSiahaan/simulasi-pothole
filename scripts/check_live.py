#!/usr/bin/env python3
"""Exercise the running simulator via its public API; save measured evidence.

Uses only an explicitly selected running demo. It changes position and controls,
and appends real sensor reports, but never clears databases.
"""
import argparse
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--url',default='http://127.0.0.1:8765')
    p.add_argument('--scenario',default='new',choices=['new','known','side','opposite','return','last'])
    p.add_argument('--offline',action='store_true')
    p.add_argument('--vision-off',action='store_true')
    p.add_argument('--seconds',type=float,default=10)
    p.add_argument('--out',default='data/evidence')
    a=p.parse_args()
    out=Path(a.out)
    out.mkdir(parents=True,exist_ok=True)
    def get(path):
        with urlopen(a.url+path,timeout=4) as r:
            return json.load(r)
    def post(path,data):
        with urlopen(Request(a.url+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'}),timeout=4) as r:
            return json.load(r)
    def snapshot(name):
        for camera in ('camera','chase'):
            with urlopen(a.url+'/snapshot/'+camera+'.jpg',timeout=4) as r:
                (out/f'{a.scenario}-{name}-{camera}.jpg').write_bytes(r.read())
    post('/api/options',{'online':not a.offline,'vision':not a.vision_off,'fusion':False,'autopilot':False})
    post('/api/reset',{'scenario':a.scenario})
    start_wall=time.monotonic()
    while True:
        s=get('/api/state')
        if all(s['health'].values()) and not s['imu']['calibrating'] and time.monotonic()-start_wall>3:
            break
        if time.monotonic()-start_wall>40:
            raise RuntimeError('Sensor atau kalibrasi tidak siap: '+str(s['health']))
        time.sleep(.15)
    start=get('/api/state')
    samples=[]
    start_t=start['pose']['time']
    seen=set()
    next_print=start_t
    try:
        while True:
            s=get('/api/state')
            elapsed=s['pose']['time']-start_t
            if elapsed>=a.seconds:
                break
            if time.monotonic()-start_wall>max(60,a.seconds*6):
                raise RuntimeError('Simulasi terlalu lambat atau terhenti')
            # Direct throttle speed hold; fixed steering tests direction/lane filters.
            throttle=max(-.3,min(1,(3-s['pose']['speed'])*.8+.12))
            post('/api/control',{'throttle':throttle,'steer':0,'brake':0})
            samples.append({k:s[k] for k in ('pose','gps','imu','buzzer','db_warning','storage','vision')})
            for source in s['buzzer']['sources']:
                if source not in seen:
                    seen.add(source)
                    snapshot(source.lower())
            if s['pose']['time']>=next_print:
                print(json.dumps({'elapsed':round(elapsed,1),'x':round(s['pose']['x'],2),'y':round(s['pose']['y'],2),
                    'z':round(s['pose']['z'],3),'speed':round(s['pose']['speed'],2),'imu_z':round(s['imu']['z'],2),
                    'buzzer':s['buzzer']['sources'],'reports':s['storage']['total_reports'],'gps':s['gps']},ensure_ascii=False),flush=True)
                next_print+=2
            time.sleep(.07)
    finally:
        post('/api/control',{'throttle':0,'steer':0,'brake':1})
    time.sleep(.5)
    end=get('/api/state')
    snapshot('end')
    result={'scenario':a.scenario,'offline':a.offline,'vision_off':a.vision_off,'start':start,
            'end':end,'sources_seen':sorted(seen),'samples':samples}
    file=out/f'{a.scenario}.json'
    file.write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print(f'Evidence: {file}; warnings={seen}; new_reports={end["storage"]["total_reports"]-start["storage"]["total_reports"]}',flush=True)


if __name__=='__main__':
    main()
