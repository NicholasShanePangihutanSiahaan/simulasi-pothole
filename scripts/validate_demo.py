#!/usr/bin/env python3
"""Run the exhibit acceptance scenarios against an isolated, running demo."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request,urlopen


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',default='data/acceptance')
    args=parser.parse_args()
    out=Path(args.out)
    outcomes=[]
    cases=[('new',8,[],{'VISION'},True),('known',7,['--vision-off'],{'DATABASE'},True),
           ('side',5,['--vision-off'],set(),False),('opposite',5,['--vision-off'],set(),False),
           ('return',7,['--vision-off'],{'DATABASE'},True),('last',8,['--offline'],{'VISION'},True)]
    for scenario,seconds,extra,warnings,imu in cases:
        subprocess.run([sys.executable,'-s','scripts/check_live.py','--scenario',scenario,
            '--seconds',str(seconds),'--out',str(out)]+extra,check=True)
        result=json.loads((out/f'{scenario}.json').read_text())
        reports=result['end']['storage']['total_reports']-result['start']['storage']['total_reports']
        seen=set(result['sources_seen'])
        success=seen==warnings and (reports>=1 if imu else reports==0)
        max_roll=max(abs(s['pose']['roll']) for s in result['samples'])
        success=success and max_roll<.3
        outcomes.append({'scenario':scenario,'pass':success,'sources':sorted(seen),'reports':reports,
                         'max_roll_rad':max_roll,'camera_fps':result['end']['vision']['fps']})
    with urlopen('http://127.0.0.1:8765/api/state') as r:
        offline=json.load(r)
    outcomes.append({'scenario':'offline_queue','pass':offline['storage']['pending']>=1,'pending':offline['storage']['pending']})
    request=Request('http://127.0.0.1:8765/api/options',data=b'{"online":true}',headers={'Content-Type':'application/json'})
    with urlopen(request) as r:
        r.read()
    start=time.monotonic()
    while time.monotonic()-start<8:
        with urlopen('http://127.0.0.1:8765/api/state') as r:
            online=json.load(r)
        if online['storage']['pending']==0 and online['storage']['cached']>offline['storage']['cached']:
            break
        time.sleep(.15)
    outcomes.append({'scenario':'reconnect_sync','pass':online['storage']['pending']==0 and online['storage']['cached']>offline['storage']['cached'],
                     'seconds':round(time.monotonic()-start,2),'cache_before':offline['storage']['cached'],'cache_after':online['storage']['cached']})
    (out/'summary.json').write_text(json.dumps(outcomes,indent=2))
    print(json.dumps(outcomes,indent=2),flush=True)
    if not all(o['pass'] for o in outcomes):
        sys.exit(1)


if __name__=='__main__':
    main()
