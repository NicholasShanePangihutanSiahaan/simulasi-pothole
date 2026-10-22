#!/usr/bin/env python3
"""Destructive acceptance test: use ONLY an isolated running demo database."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request,urlopen


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--allow-reset-test-database',action='store_true',required=True)
    p.add_argument('--lap',action='store_true')
    a=p.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    checks=[]
    def api(path,data=None):
        req=Request(a.url+path,data=json.dumps(data).encode() if data is not None else None,
                    headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=10) as r:
            return json.load(r)
    def check(name,ok,**details):
        row=dict(name=name,passed=bool(ok),**details);checks.append(row)
        print(json.dumps(row),flush=True)
        (out/'summary.json').write_text(json.dumps(checks,indent=2))
    def drive(scenario,seconds,extra=(),label=None):
        directory=out/(label or scenario)
        subprocess.run([sys.executable,'-s','scripts/check_live.py','--url',a.url,
            '--scenario',scenario,'--seconds',str(seconds),'--out',str(directory),*extra],check=True)
        result=json.loads((directory/f'{scenario}.json').read_text())
        count=result['end']['storage']['total_reports']-result['start']['storage']['total_reports']
        return result,count
    api('/api/control',{'brake':1})
    api('/api/database/reset',{'confirm':'RESET POTHOLE DATABASE'})
    api('/api/options',{'imu':False,'database':False})
    r,n=drive('new',7,label='vision_only')
    check('vision_only_never_stored',n==0 and 'VISION' in r['sources_seen'],reports=n)
    api('/api/options',{'imu':True})
    r,n=drive('new',7)
    check('pothole_imu_and_vision',n==1 and 'VISION' in r['sources_seen'],reports=n)
    for scenario,seconds in [('crack',6),('bump',7),('paving',26)]:
        r,n=drive(scenario,seconds)
        check('reject_'+scenario,n==0 and not r['sources_seen'],reports=n,sources=r['sources_seen'])
    r,n=drive('known',7,['--vision-off'])
    check('imu_without_vision',n==1,reports=n)
    r,n=drive('small',7)
    check('small_pothole_C',n==1 and 'VISION' in r['sources_seen'],reports=n,sources=r['sources_seen'])
    api('/api/options',{'database':True})
    r,n=drive('return',7,['--vision-off'])
    check('database_approach', 'DATABASE' in r['sources_seen'],sources=r['sources_seen'])
    r,n=drive('last',7,['--offline'])
    check('offline_queue',n==1 and r['end']['storage']['pending']>=1,reports=n)
    response=api('/api/database/reset',{'confirm':'RESET POTHOLE DATABASE'})
    empty=api('/api/state')['storage']
    check('reset_including_offline_queue',not any(empty.values()),storage=empty,backups=response['backups'])
    api('/api/options',{'online':True})
    time.sleep(3)
    empty=api('/api/state')['storage']
    check('sync_does_not_restore_deleted_data',not any(empty.values()),storage=empty)
    if a.lap:
        r,n=drive('start',220,['--auto'])
        poses=[s['pose'] for s in r['samples']]
        track=r['end']['config']['track']
        # All four stadium quadrants and return past the start in a single drive.
        completed=(max(p['x'] for p in poses)>track['straight']+25 and
                   min(p['x'] for p in poses)<-25 and max(p['y'] for p in poses)>58 and
                   r['end']['pose']['x']>4 and r['end']['pose']['y']<2)
        stable=max(abs(p['roll']) for p in poses)<.35 and min(p['z'] for p in poses)>.4
        check('complete_stadium_lap',completed and stable,reports=n,end=r['end']['pose'])
    if not all(c['passed'] for c in checks):
        sys.exit(1)


if __name__=='__main__':
    main()
