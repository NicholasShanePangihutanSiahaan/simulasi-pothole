"""Stadium geometry for scenery/navigation only; never used by detectors."""
import math


def length(cfg):
    return 2*cfg['straight']+2*math.pi*cfg['radius']


def point(s, cfg, offset=0):
    l, r = cfg['straight'], cfg['radius']
    s %= length(cfg)
    if s < l:
        x, y, yaw = s, 0, 0
    elif s < l+math.pi*r:
        a = (s-l)/r
        x, y, yaw = l+r*math.sin(a), r-r*math.cos(a), a
    elif s < 2*l+math.pi*r:
        x, y, yaw = 2*l+math.pi*r-s, 2*r, math.pi
    else:
        a = (s-2*l-math.pi*r)/r
        x, y, yaw = -r*math.sin(a), r+r*math.cos(a), math.pi+a
    return x-offset*math.sin(yaw), y+offset*math.cos(yaw), yaw


def project(x, y, cfg):
    l, r = cfg['straight'], cfg['radius']
    candidates = [max(0, min(l, x)), l+math.pi*r+max(0, min(l, l-x))]
    a = max(0, min(math.pi, math.atan2(x-l, r-y)))
    b = max(0, min(math.pi, math.atan2(-x, y-r)))
    candidates += [l+r*a, 2*l+math.pi*r+r*b]
    return min(candidates, key=lambda s: math.hypot(point(s, cfg)[0]-x, point(s, cfg)[1]-y)) % length(cfg)
