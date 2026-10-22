"""Sensor-only decisions. This module never imports the world pothole list."""
from collections import deque
import math
import statistics

EARTH_RADIUS = 6378137.0


def to_xy(lat, lon, origin):
    return (math.radians(lon-origin['longitude'])*EARTH_RADIUS*math.cos(math.radians(origin['latitude'])),
            math.radians(lat-origin['latitude'])*EARTH_RADIUS)


def to_gps(x, y, origin):
    return (origin['latitude']+math.degrees(y/EARTH_RADIUS),
            origin['longitude']+math.degrees(x/(EARTH_RADIUS*math.cos(math.radians(origin['latitude'])))))


def distance_m(a, b):
    mean = math.radians((a['latitude']+b['latitude'])/2)
    return EARTH_RADIUS*math.hypot(math.radians(a['latitude']-b['latitude']),
                                 math.radians(a['longitude']-b['longitude'])*math.cos(mean))


def quaternion_euler(q):
    w,x,y,z = q.w,q.x,q.y,q.z
    return (math.atan2(2*(w*x+y*z),1-2*(x*x+y*y)),
            math.asin(max(-1,min(1,2*(w*y-z*x)))),
            math.atan2(2*(w*z+x*y),1-2*(y*y+z*z)))


def vertical_acceleration(accel, q):
    # Rotate specific force from IMU body coordinates into world Z, subtract gravity.
    return (2*(q.x*q.z-q.w*q.y)*accel.x + 2*(q.y*q.z+q.w*q.x)*accel.y
            + (1-2*(q.x*q.x+q.y*q.y))*accel.z - 9.81)


class ImuDetector:
    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.window = deque(maxlen=self.cfg['window'])
        self.filtered = 0.0
        self.last_t = None
        self.last_event = -1e9
        self.start = None
        self.baseline = []
        self.bias = 0
        self.candidate = None
        self.quiet_since = None
        self.pitch_baseline = 0.

    def update(self, t, z, speed, pitch=None):
        if self.last_t is not None and t <= self.last_t:
            self.reset()
        if self.start is None:
            self.start = t
        dt = min(.05, max(.001, t-self.last_t)) if self.last_t is not None else .01
        self.last_t = t
        if t-self.start < 1.4 and abs(speed) < .15:
            self.baseline.append(z)
            self.bias = statistics.mean(self.baseline[-100:])
        z -= self.bias
        previous = self.filtered
        self.filtered += dt/(.018+dt)*(z-self.filtered)
        diff = abs(self.filtered-previous)
        self.window.append(self.filtered)
        std = statistics.pstdev(self.window) if len(self.window)>2 else 0
        triggered = False
        event_time = t
        classification = 'normal'
        active = t-self.start>2 and abs(speed)>.7 and t-self.last_event>self.cfg['cooldown']
        if not active:
            self.candidate=None
            if pitch is not None:
                self.pitch_baseline=pitch
        elif self.candidate is None and abs(self.filtered)>1.2:
            self.candidate={'start':t,'first':'unknown',
                            'velocity':0.,'displacement':0.,'depth':0.,'peak':0.,'negative':0.,
                            'pitch_base':self.pitch_baseline,'pitch_first':'unknown'}
            self.quiet_since=None
        elif self.candidate is None and pitch is not None:
            self.pitch_baseline+=.03*(pitch-self.pitch_baseline)
        if self.candidate:
            c=self.candidate
            c['velocity']+=self.filtered*dt
            c['displacement']+=c['velocity']*dt
            c['depth']=min(c['depth'],c['displacement'])
            c['peak']=max(c['peak'],abs(self.filtered))
            c['negative']+=max(0,-self.filtered)*dt
            # Decide the initial direction from a short integrated excursion,
            # not a single mesh-contact impulse (which can have either sign).
            if c['first']=='unknown':
                if c['displacement']<-.012:
                    c['first']='drop'
                elif c['displacement']>.012:
                    c['first']='rise'
            if pitch is not None and c['pitch_first']=='unknown':
                delta_pitch=pitch-c['pitch_base']
                # IMU frame: positive pitch means front wheel goes DOWN.
                # Pitch resolves signed acceleration bias from sampled contact
                # impulses. It is a measured IMU orientation, not world metadata.
                if delta_pitch>.008:
                    c['pitch_first']='drop'
                elif delta_pitch<-.008:
                    c['pitch_first']='rise'
            first=c['pitch_first'] if pitch is not None else c['first']
            classification='bump/rejected' if first=='rise' else 'candidate'
            # A pothole begins with unloading/drop, then an upward edge impact.
            # A speed bump begins with upward acceleration; paving's shallow
            # repeated joints do not accumulate a centimetre-scale descent.
            triggered=(first=='drop' and c['depth']<-.012 and c['negative']>.12
                       and self.filtered>2.0 and c['peak']>self.cfg['z_threshold']
                       and t-c['start']<1.4)
            if triggered:
                classification='pothole'
                event_time=c['start']
            if abs(self.filtered)<.65:
                if self.quiet_since is None:
                    self.quiet_since=t
            else:
                self.quiet_since=None
            if triggered or (self.quiet_since is not None and t-self.quiet_since>.35) or t-c['start']>2.0:
                self.candidate=None
        if triggered:
            self.last_event = t
        return {'z': self.filtered, 'raw_z': z, 'diff': diff, 'std': std,
                'peak':max(abs(v) for v in self.window),
                'event_time':event_time, 'classification':classification,
                'triggered': triggered, 'calibrating': t-self.start <= 2}


class GPSHistory:
    def __init__(self):
        self.samples = deque(maxlen=80)

    def add(self, t, lat, lon):
        if self.samples and t <= self.samples[-1][0]:
            self.samples.clear()
        self.samples.append((t,lat,lon))

    def interpolate(self, t):
        for a,b in zip(self.samples, list(self.samples)[1:]):
            if a[0] <= t <= b[0] and b[0]-a[0] <= .6:
                f = (t-a[0])/(b[0]-a[0])
                return {'latitude':a[1]+f*(b[1]-a[1]), 'longitude':a[2]+f*(b[2]-a[2])}
        return None


def nearby_warning(x, y, yaw, speed, steer, records, origin, cfg):
    """Warn for hazards ahead on the projected steering arc, never just a radius."""
    if speed < cfg['min_speed']:
        return None
    radius = min(cfg['radius'], max(6.0, speed*cfg['lookahead_seconds']))
    curvature = math.tan(steer*.48)/1.16
    best = None
    for row in records:
        hx,hy = to_xy(row['latitude'],row['longitude'],origin)
        dx,dy = hx-x,hy-y
        forward = dx*math.cos(yaw)+dy*math.sin(yaw)
        lateral = -dx*math.sin(yaw)+dy*math.cos(yaw)
        # Closing along current velocity is required (exclude behind/away).
        if forward <= .25 or math.hypot(dx,dy) > radius+cfg['corridor']:
            continue
        nearest = (1e9,0)
        for i in range(1,61):
            s = radius*i/60
            px = math.sin(curvature*s)/curvature if abs(curvature)>1e-5 else s
            py = (1-math.cos(curvature*s))/curvature if abs(curvature)>1e-5 else 0
            d = math.hypot(forward-px,lateral-py)
            if d < nearest[0]:
                nearest = (d,s)
        if nearest[0] <= cfg['corridor'] and (best is None or nearest[1]<best['distance']):
            best = {'id':row['id'], 'distance':nearest[1], 'eta':nearest[1]/speed,
                    'latitude':row['latitude'], 'longitude':row['longitude']}
    return best
