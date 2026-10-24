#!/usr/bin/env python3
"""Measure real Gazebo IMU histories for flat road, paving, bump and potholes.

--launch uses a temporary database and shuts down only its own launcher.
Never clears a database. A supplied --url session will be driven/reset in place.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8895')
    parser.add_argument('--launch',action='store_true')
    parser.add_argument('--out',default='data/imu-threshold-review.json')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    def api(path,body=None):
        req=Request(args.url+path,data=json.dumps(body).encode() if body is not None else None,
                    headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=5) as response:
            return json.load(response)
    child=None
    logfile=None
    try:
        if args.launch:
            if args.url!='http://127.0.0.1:8895':
                parser.error('--launch uses ports 8895/8896; omit --url')
            data=Path(tempfile.mkdtemp(prefix='pothole-imu-review-'))
            logfile=(data/'launcher.log').open('w')
            child=subprocess.Popen(['bash','start.sh','--headless','--skip-build','--port','8895',
                                    '--server-port','8896','--data-dir',str(data),'--no-seed'],
                                   cwd=root,stdout=logfile,stderr=subprocess.STDOUT)
            print('Isolated test data:',data,flush=True)
        deadline=time.monotonic()+70
        while True:
            if child is not None and child.poll() is not None:
                raise RuntimeError('Launcher exited; see '+str(data/'launcher.log'))
            try:
                s=api('/api/state')
                if s['health']['gazebo'] and s['health']['imu']:
                    break
            except (URLError,OSError):
                pass
            if time.monotonic()>deadline:
                raise RuntimeError('Gazebo IMU did not become ready')
            time.sleep(.2)
        api('/api/options',{'vision':False,'database':False,'autopilot':False})
        results=[]
        for scenario,seconds,expected in [('start',3,0),('bump',7,0),('paving',10,0),('new',7,1),('small',7,1)]:
            api('/api/reset',{'scenario':scenario})
            deadline=time.monotonic()+40
            while True:
                s=api('/api/state')
                if not s['imu']['calibrating']:
                    break
                if time.monotonic()>deadline:
                    raise RuntimeError('Calibration timeout')
                time.sleep(.1)
            start=s['pose']['time']
            reports=s['storage']['total_reports']
            history={}
            assessments=[]
            deadline=time.monotonic()+100
            while s['pose']['time']-start<seconds:
                throttle=max(-.3,min(1,(3-s['pose']['speed'])*.8+.12))
                api('/api/control',{'throttle':throttle,'steer':0,'brake':0})
                for p in s['imu_history']:
                    if p[0]>=start:
                        history[p[0]]=p
                if s['imu'].get('assessment'):
                    assessments.append(s['imu']['assessment'])
                if time.monotonic()>deadline:
                    raise RuntimeError('Simulation stalled')
                time.sleep(.07)
                s=api('/api/state')
            api('/api/control',{'throttle':0,'steer':0,'brake':1})
            time.sleep(.6)
            end=api('/api/state')
            samples=sorted(history.values())
            threshold=s['config']['imu']['z_threshold']
            count=end['storage']['total_reports']-reports
            result={'scenario':scenario,'threshold':threshold,
                    'peak_abs_az':round(max(abs(p[1]) for p in samples),3),
                    'samples_over_threshold':sum(abs(p[1])>threshold for p in samples),
                    'classifications':dict(Counter(p[2] for p in samples)),
                    'new_reports':count,'expected_reports':expected,'passed':count==expected,
                    'imu_history':samples,'assessments':assessments}
            results.append(result)
            print(json.dumps({k:v for k,v in result.items() if k not in ('imu_history','assessments')}),flush=True)
        out=root/args.out
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps({'target_speed_m_s':3,'results':results},indent=2))
        print('Evidence:',out,flush=True)
        if not all(r['passed'] for r in results):
            raise RuntimeError('Surface classification differs from expected; inspect evidence')
    finally:
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGINT)
            try:
                child.wait(timeout=25)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=15)
        if logfile:
            logfile.close()


if __name__=='__main__':
    main()
