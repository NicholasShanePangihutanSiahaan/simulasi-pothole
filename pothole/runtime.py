import json
import math
import os
import threading
import time
from collections import deque
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

import cv2
import numpy as np
cv2.setNumThreads(2)

# Compatibility with distro Gazebo messages if user site-packages has protobuf 4+.
os.environ.setdefault('PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION','python')
from gz.transport13 import Node
from gz.msgs10.imu_pb2 import IMU
from gz.msgs10.image_pb2 import Image
from gz.msgs10.navsat_pb2 import NavSat
from gz.msgs10.odometry_pb2 import Odometry
from gz.msgs10.pose_pb2 import Pose
from gz.msgs10.twist_pb2 import Twist

from .core import ImuDetector, GPSHistory, nearby_warning, quaternion_euler, to_xy, vertical_acceleration
from .storage import Store
from .vision import Detector

ROOT=Path(__file__).resolve().parents[1]


def stamp(msg):
    return msg.header.stamp.sec+msg.header.stamp.nsec*1e-9


class Runtime:
    def __init__(self, data, server_url):
        self.cfg=json.loads((ROOT/'config/demo.json').read_text())
        self.store=Store(data)
        self.server_url=server_url.rstrip('/')
        self.lock=threading.RLock()
        self.stop=threading.Event()
        self.node=Node()
        self.control_pub=self.node.advertise('/capstone/control',Twist)
        self.reset_pub=self.node.advertise('/capstone/reset',Pose)
        self.detector=ImuDetector(self.cfg['imu'])
        self.vision_detector=Detector(self.cfg['vision'])
        self.gps_history=GPSHistory()
        self.pending_fixes=[]
        self.history=deque(maxlen=450)
        self.events=deque(maxlen=60)
        self.pose={'x':4.,'y':-2.,'z':.72,'yaw':0.,'pitch':0.,'roll':0.,'speed':0.,'time':0.}
        self.gps=None
        self.imu={'z':0,'raw_z':0,'diff':0,'std':0,'calibrating':True,'triggered':False}
        self.vision={'detections':[],'fps':0.,'latency_ms':0.,'algorithm':self.vision_detector.name}
        self.options={'online':True,'vision':True,'imu':True,'database':True,'fusion':False,'autopilot':False}
        self.command={'throttle':0.,'steer':0.,'brake':1.}
        self.last_input=0
        self.last_client=0
        self.last_odom=0
        self.last_imu=0
        self.last_gps=0
        self.last_camera=0
        self.last_vision_detection=-1e9
        self.last_vision_event=-1e9
        self.last_reset_wall=0
        self.last_sync=0
        self.sync_error='Menunggu sinkronisasi pertama'
        self.sync_ms=0
        self.db_warning=None
        self.buzzer={'active':False,'sources':[]}
        self.frames={'camera':None,'chase':None}
        self.frame_seq={'camera':0,'chase':0}
        self.raw_frames={}
        self.camera_times=deque(maxlen=30)
        self.log_path=Path(data).parent/'events.jsonl'
        self.event('SISTEM','Perangkat siap. Kalibrasi IMU selama 2 detik; jangan bergerak.','info')
        self.node.subscribe(Odometry,'/capstone/odometry',self.on_odom)
        self.node.subscribe(IMU,'/capstone/imu',self.on_imu)
        self.node.subscribe(NavSat,'/capstone/gps',self.on_gps)
        self.node.subscribe(Image,'/capstone/camera',lambda m:self.on_image('camera',m))
        self.node.subscribe(Image,'/capstone/chase',lambda m:self.on_image('chase',m))
        for target in (self.control_loop,self.sync_loop,self.image_loop):
            threading.Thread(target=target,daemon=True).start()

    def event(self, kind, message, level='info'):
        with self.lock:
            row={'time':time.strftime('%H:%M:%S'),'wall':time.time(),'sim':round(self.pose['time'],3),
                 'kind':kind,'message':message,'level':level}
            self.events.appendleft(row)
            with self.log_path.open('a') as f:
                f.write(json.dumps(row,ensure_ascii=False)+'\n')

    def on_odom(self,msg):
        roll,pitch,yaw=quaternion_euler(msg.pose.orientation)
        with self.lock:
            p,v=msg.pose.position,msg.twist.linear
            self.pose={'x':p.x,'y':p.y,'z':p.z,'yaw':yaw,'roll':roll,'pitch':pitch,
                       'speed':v.x*math.cos(yaw)+v.y*math.sin(yaw),'time':stamp(msg)}
            self.last_odom=time.monotonic()

    def on_imu(self,msg):
        z=vertical_acceleration(msg.linear_acceleration,msg.orientation)
        t=stamp(msg)
        with self.lock:
            self.last_imu=time.monotonic()
            self.imu=self.detector.update(t,z,self.pose['speed'])
            self.history.append([round(t,3),round(self.imu['z'],3)])
            if self.imu['triggered'] and self.options['imu']:
                if self.options['fusion'] and t-self.last_vision_detection>2.0:
                    self.event('IMU','Guncangan tanpa konfirmasi vision; mode validasi ganda menahan laporan.','info')
                else:
                    self.pending_fixes.append({'time':t,'peak':self.imu['peak'],
                        'std':self.imu['std'],'source':'imu+vision' if t-self.last_vision_detection<=2 else 'imu',
                        'wall':time.monotonic(),'timestamp':time.time(),'speed':self.pose['speed']})

    def on_gps(self,msg):
        t=stamp(msg)
        if not math.isfinite(msg.latitude_deg) or not math.isfinite(msg.longitude_deg):
            return
        if not (-90<=msg.latitude_deg<=90 and -180<=msg.longitude_deg<=180):
            return
        with self.lock:
            self.last_gps=time.monotonic()
            self.gps={'latitude':msg.latitude_deg,'longitude':msg.longitude_deg,'time':t}
            self.gps_history.add(t,msg.latitude_deg,msg.longitude_deg)
            remaining=[]
            for report in self.pending_fixes:
                fix=self.gps_history.interpolate(report['time'])
                if fix:
                    payload={k:v for k,v in report.items() if k!='wall'}
                    payload.update(fix,device='sepeda-demo-01')
                    self.store.add_report(payload)
                    self.event('IMU',f"Anomali tersimpan lokal · {fix['latitude']:.6f}, {fix['longitude']:.6f} · |az| {report['peak']:.1f} m/s²",'imu')
                elif time.monotonic()-report['wall']<2:
                    remaining.append(report)
                else:
                    self.event('GPS','Laporan IMU tidak dipetakan: sampel GPS tidak cukup untuk interpolasi.','warn')
            self.pending_fixes=remaining

    def on_image(self,kind,msg):
        # Keep transport callbacks short; the worker processes only the newest image.
        with self.lock:
            self.raw_frames[kind]=(msg.width,msg.height,msg.step,bytes(msg.data),stamp(msg))

    def image_loop(self):
        while not self.stop.wait(.005):
            with self.lock:
                pending=self.raw_frames
                self.raw_frames={}
            for kind,(w,h,step,data,t) in pending.items():
                if not w or not h or len(data)<h*step or step<w*3:
                    continue
                try:
                    start=time.monotonic()
                    rgb=np.frombuffer(data,dtype=np.uint8).reshape(h,step)[:,:w*3].reshape(h,w,3)
                    if kind=='camera':
                        with self.lock:
                            enabled=self.options['vision']
                        detections=self.vision_detector.detect(rgb) if enabled else []
                        bgr=self.vision_detector.annotate(rgb,detections,enabled)
                        with self.lock:
                            self.last_camera=time.monotonic()
                            self.camera_times.append(start)
                            fps=(len(self.camera_times)-1)/(start-self.camera_times[0]) if len(self.camera_times)>1 else 0
                            self.vision={'detections':detections,'fps':round(fps,1),
                                'latency_ms':round((time.monotonic()-start)*1000,1), 'algorithm':self.vision_detector.name}
                            if detections:
                                self.last_vision_detection=t
                                if t-self.last_vision_event>2:
                                    self.last_vision_event=t
                                    self.event('VISION',f"Dugaan lubang pada citra · sekitar {detections[0]['distance']:.1f} m · buzzer aktif",'vision')
                    else:
                        bgr=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
                    ok,jpg=cv2.imencode('.jpg',bgr,[cv2.IMWRITE_JPEG_QUALITY,83])
                    if ok:
                        with self.lock:
                            self.frames[kind]=jpg.tobytes()
                            self.frame_seq[kind]+=1
                except (ValueError,cv2.error) as exc:
                    self.event('KAMERA',str(exc),'warn')

    def set_control(self,data):
        values={key:float(data.get(key,0)) for key in ('throttle','steer','brake')}
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError('Kontrol harus bilangan hingga')
        with self.lock:
            self.command={key:max(0 if key=='brake' else -1,min(1,v)) for key,v in values.items()}
            self.last_input=time.monotonic()
            self.last_client=self.last_input
            if any(abs(self.command[k])>.08 for k in ('throttle','steer')) or self.command['brake']>.1:
                self.options['autopilot']=False

    def set_options(self,data):
        with self.lock:
            for key,value in data.items():
                if key not in self.options or not isinstance(value,bool):
                    raise ValueError('Opsi tidak valid')
            self.options.update(data)
            if data.get('autopilot'):
                self.last_client=time.monotonic()
            if 'online' in data:
                self.event('JARINGAN','Online: antrean akan dikirim ke server.' if data['online'] else 'Offline: laporan tetap disimpan dan peringatan database memakai cache lokal.','sync')

    def reset(self,scenario):
        presets={'start':(4,-2,0),'new':(16,-2,0),'known':(44,-2,0),'opposite':(63,-2,0),
                 'return':(64,-2,math.pi),'side':(46,2,0),'last':(106,-2,0)}
        if scenario not in presets:
            raise ValueError('Skenario tidak dikenal')
        x,y,yaw=presets[scenario]
        msg=Pose()
        msg.position.x=x
        msg.position.y=y
        msg.orientation.z=math.sin(yaw/2)
        msg.orientation.w=math.cos(yaw/2)
        with self.lock:
            self.options['autopilot']=False
            self.command={'throttle':0.,'steer':0.,'brake':1.}
            self.detector.reset()
            self.gps_history.samples.clear()
            self.pending_fixes=[]
            self.history.clear()
            self.gps=None
            self.last_gps=0
            self.last_vision_detection=-1e9
            self.last_reset_wall=time.monotonic()
        self.reset_pub.publish(msg)
        self.event('SKENARIO',f'Posisi {scenario}; tunggu kalibrasi 2 detik. Database tetap tersimpan.','info')

    def control_loop(self):
        last_sources=[]
        while not self.stop.wait(.05):
            now=time.monotonic()
            with self.lock:
                cmd=dict(self.command)
                if self.options['autopilot'] and now-self.last_client>.8:
                    self.options['autopilot']=False
                if self.options['autopilot'] and now-self.last_odom<1 and not self.imu['calibrating']:
                    # Exhibit assist follows the straight demonstration lane, no world hazards.
                    yaw=self.pose['yaw']
                    target=math.atan2((-2-self.pose['y'])*.7,4)
                    error=math.atan2(math.sin(target-yaw),math.cos(target-yaw))
                    cmd={'throttle':max(-.4,min(1,(3-self.pose['speed'])*.8+.12)),
                         'steer':max(-1,min(1,error*1.8)),'brake':0.}
                    if self.pose['x']>136:
                        self.options['autopilot']=False
                        cmd={'throttle':0,'steer':0,'brake':1}
                elif now-self.last_input>.5 or self.imu['calibrating']:
                    cmd={'throttle':0,'steer':0,'brake':1}
                msg=Twist()
                msg.linear.x=float(cmd['throttle'])
                msg.linear.y=float(cmd['brake'])
                msg.angular.z=float(cmd['steer'])
                self.control_pub.publish(msg)
                self.db_warning=None
                if self.options['database'] and self.gps and now-self.last_gps<1 and now-self.last_odom<1:
                    x,y=to_xy(self.gps['latitude'],self.gps['longitude'],self.cfg['origin'])
                    self.db_warning=nearby_warning(x,y,self.pose['yaw'],self.pose['speed'],cmd['steer'],
                        self.store.cached(),self.cfg['origin'],self.cfg['warning'])
                sources=[]
                if (self.options['vision'] and now-self.last_camera<.7 and now-self.last_odom<1
                    and 0<=self.pose['time']-self.last_vision_detection<.45):
                    sources.append('VISION')
                if self.db_warning:
                    sources.append('DATABASE')
                if sources!=last_sources and sources:
                    self.event('BUZZER',' + '.join(sources)+' · peringatan aktif','warn')
                self.buzzer={'active':bool(sources),'sources':sources}
                last_sources=sources
                if self.pending_fixes and now-self.last_gps>2:
                    expired=[p for p in self.pending_fixes if now-p['wall']>2]
                    if expired:
                        self.pending_fixes=[p for p in self.pending_fixes if now-p['wall']<=2]
                        self.event('GPS','Guncangan terdeteksi, tetapi GPS tidak tersedia; tidak ada koordinat yang dikarang.','warn')

    def sync_loop(self):
        while not self.stop.is_set():
            with self.lock:
                online=self.options['online']
            if online:
                start=time.monotonic()
                try:
                    pending=self.store.pending()
                    if pending:
                        req=Request(self.server_url+'/api/reports',data=json.dumps({'reports':pending}).encode(),
                                    headers={'Content-Type':'application/json'})
                        with urlopen(req,timeout=2) as response:
                            accepted=json.load(response)['accepted']
                        self.store.mark_synced(set(accepted)&{r['event_id'] for r in pending})
                        if accepted:
                            self.event('SYNC',f'{len(accepted)} laporan diterima server.','sync')
                    with urlopen(self.server_url+'/api/potholes',timeout=2) as response:
                        rows=json.load(response)['potholes']
                    self.store.replace_cache(rows)
                    with self.lock:
                        self.last_sync=time.time()
                        self.sync_error=''
                        self.sync_ms=round((time.monotonic()-start)*1000,1)
                except (URLError,OSError,ValueError,KeyError) as exc:
                    with self.lock:
                        self.sync_error=str(exc)
            self.stop.wait(self.cfg['sync']['interval'])

    def state(self):
        with self.lock:
            now=time.monotonic()
            return {'pose':dict(self.pose),'gps':dict(self.gps) if self.gps else None,
                'imu':dict(self.imu),'imu_history':list(self.history),'vision':dict(self.vision),
                'options':dict(self.options),'buzzer':dict(self.buzzer),'db_warning':self.db_warning,
                'storage':self.store.counts(),'potholes':self.store.cached(),'events':list(self.events)[:30],
                'sync':{'last':self.last_sync,'error':self.sync_error,'ms':self.sync_ms},
                'health':{'gazebo':now-self.last_odom<1.5,'imu':now-self.last_imu<1.5,
                          'gps':now-self.last_gps<1.5,'camera':now-self.last_camera<1.5},
                'config':{'origin':self.cfg['origin'],'imu':self.cfg['imu'],'warning':self.cfg['warning']}}

    def close(self):
        self.stop.set()
        msg=Twist()
        msg.linear.y=1
        self.control_pub.publish(msg)
