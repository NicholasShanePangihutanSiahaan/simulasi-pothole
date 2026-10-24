#!/usr/bin/env python3
"""Characterise the unchanged detector with real Gazebo sensors, isolated data.

Coordinates below define test manoeuvres only, never detector inputs.
"""
import json
import argparse
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from urllib.request import Request,urlopen
from urllib.error import URLError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['GZ_PARTITION']='pothole-capstone-8895'
os.environ['GZ_IP']='127.0.0.1'
os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION']='python'
from gz.transport13 import Node
from gz.msgs10.pose_pb2 import Pose
from pothole.track import point,project,length

CFG=json.loads((ROOT/'config/demo.json').read_text())
TRACK=CFG['track']
OUT=ROOT/'data/imu-characterisation'


def api(path,body=None):
    req=Request('http://127.0.0.1:8895'+path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=5) as r:
        return json.load(r)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--followups',action='store_true',help='Repeat slow C twice and test centred slalom at 3/6 m/s')
    args=parser.parse_args()
    out=OUT/'followups' if args.followups else OUT
    out.mkdir(parents=True,exist_ok=True)
    data=Path(tempfile.mkdtemp(prefix='pothole-characterisation-'))
    log=(data/'launcher.log').open('w')
    child=subprocess.Popen(['bash','start.sh','--headless','--skip-build','--port','8895',
                            '--server-port','8896','--data-dir',str(data),'--no-seed'],
                           cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    results=[]
    try:
        deadline=time.monotonic()+80
        while True:
            if child.poll() is not None:
                raise RuntimeError('Launcher failed: '+str(data/'launcher.log'))
            try:
                state=api('/api/state')
                if state['health']['imu'] and state['health']['gazebo']:
                    break
            except (URLError,OSError):pass
            if time.monotonic()>deadline:raise RuntimeError('Sensor startup timeout')
            time.sleep(.2)
        node=Node()
        reset=node.advertise('/capstone/reset',Pose)
        api('/api/options',{'vision':False,'database':False,'autopilot':False})
        cases=[]
        # Long run-ups let the higher target speeds be reached before impact.
        for speed in (1.5,3.,6.):
            cases.extend([
                ('flat',speed,(120,2,0),150,False),
                ('bump',speed,(68,-2,0),103,False),
                ('paving',speed,(136,62,math.pi),100,False),
                ('pothole_A',speed,(4,-2,0),29,True),
                ('pothole_C',speed,(46,2,0),88,True),
            ])
        for speed in (3.,6.):
            cases.extend([('curve',speed,(*point(150,TRACK,-2)[:2],0),210,False),
                          ('slalom',speed,(105,2,0),148,False)])
        if args.followups:
            cases=[('pothole_C',1.5,(46,2,0),88,True)]*2
            cases += [('slalom_centered',speed,(105,2,0),148,False) for speed in (3.,6.)]
        for number,(name,target,start,end,expected) in enumerate(cases,1):
            api('/api/reset',{'scenario':'start'})
            msg=Pose();msg.position.x=start[0];msg.position.y=start[1]
            msg.orientation.w=math.cos(start[2]/2);msg.orientation.z=math.sin(start[2]/2)
            for _ in range(4):reset.publish(msg);time.sleep(.08)
            deadline=time.monotonic()+40
            while True:
                s=api('/api/state')
                if (not s['imu']['calibrating'] and math.hypot(s['pose']['x']-start[0],s['pose']['y']-start[1])<.4):break
                if time.monotonic()>deadline:raise RuntimeError('Reset/calibration timeout')
                time.sleep(.08)
            before=s['storage']['total_reports'];begin=s['pose']['time']
            snapshots=[];history={};maneuver_start=None
            deadline=time.monotonic()+150
            while True:
                p=s['pose'];t=p['time']
                for sample in s['imu_history']:
                    if sample[0]>=begin:history[sample[0]]=sample
                snapshots.append({'time':t,'pose':p,'imu':s['imu']})
                if name=='curve':
                    station=project(p['x'],p['y'],TRACK)
                    finished=station>=end
                    tx,ty,_=point(station+5,TRACK,-2)
                    error=math.atan2(math.sin(math.atan2(ty-p['y'],tx-p['x'])-p['yaw']),
                                     math.cos(math.atan2(ty-p['y'],tx-p['x'])-p['yaw']))
                    curvature=2*math.sin(error)/max(1,math.hypot(tx-p['x'],ty-p['y']))
                    steer=max(-1,min(1,math.atan(1.16*curvature)/.48))
                else:
                    finished=p['x']<=end if name=='paving' else p['x']>=end
                    steer=0
                    if name.startswith('slalom') and p['x']>=130:
                        if maneuver_start is None:maneuver_start=t
                        phase=(t-maneuver_start)*3.5
                        steer=.38*(math.cos(phase) if name=='slalom_centered' else math.sin(phase))
                if finished:break
                if time.monotonic()>deadline:raise RuntimeError('Driving timeout '+name)
                throttle=max(-.5,min(1,(target-p['speed'])*.8+.12))
                api('/api/control',{'throttle':throttle,'steer':steer,'brake':0})
                time.sleep(.04)
                s=api('/api/state')
            api('/api/control',{'throttle':0,'steer':0,'brake':1})
            time.sleep(.8)
            final=api('/api/state')
            count=final['storage']['total_reports']-before
            samples=sorted(history.values())
            events=[p for p in samples if p[2]=='pothole']
            # Geometric checks are evaluation ground truth, not classification.
            deviations=[]
            for snap in snapshots:
                p=snap['pose'];station=project(p['x'],p['y'],TRACK)
                cx,cy,_=point(station,TRACK)
                deviations.append(math.hypot(p['x']-cx,p['y']-cy))
            zone={'bump':(92,100),'pothole_A':(22,27),'pothole_C':(81,86),'paving':(100,110),'flat':(140,150),'slalom':(130,148),'slalom_centered':(130,148)}
            impact=[r for r in snapshots if (180<=project(r['pose']['x'],r['pose']['y'],TRACK)<=210 if name=='curve' else zone[name][0]<=r['pose']['x']<=zone[name][1])]
            assessments=[r['imu']['assessment'] for r in snapshots if r['imu'].get('assessment')]
            observed={key:sum(a['checks'][key] for a in assessments) for key in ('amplitude','drop','descent','impulse','rebound','duration')}
            event_details=[]
            for event in events:
                closest=min(snapshots,key=lambda r:abs(r['time']-event[0]))
                event_details.append({'time':event[0],'pose':closest['pose'],'az':event[1]})
            summary={'case':name,'target_speed':target,
                     'measured_speed_range':[round(min(r['pose']['speed'] for r in impact),2),round(max(r['pose']['speed'] for r in impact),2)] if impact else None,
                     'peak_abs_az':round(max(abs(p[1]) for p in samples),3),
                     'over_threshold_samples':sum(abs(p[1])>4.5 for p in samples),
                     'confirmed_events':len(events),'new_reports':count,'expected_pothole':expected,
                     'max_lateral_from_center':round(max(deviations),3),
                     'left_road':max(deviations)>TRACK['width']/2,
                     'max_abs_roll':round(max(abs(r['pose']['roll']) for r in snapshots),3),
                     'checks_true_in_polled_assessments':observed,
                     'event_details':event_details}
            results.append(summary)
            filename=f'{number:02d}-{name}-{target:g}.json' if args.followups else f'{name}-{target:g}.json'
            (out/filename).write_text(json.dumps({'summary':summary,'snapshots':snapshots,'imu_history':samples},indent=2))
            (out/'summary.json').write_text(json.dumps({'isolated_data':str(data),'cases':results},indent=2))
            print(f'{number}/{len(cases)} '+json.dumps(summary),flush=True)
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGINT)
            try:child.wait(timeout=25)
            except subprocess.TimeoutExpired:
                child.terminate();child.wait(timeout=15)
        log.close()


if __name__=='__main__':main()
