import json
import math
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest

from pothole.core import GPSHistory, ImuDetector, nearby_warning, to_gps, to_xy, vertical_acceleration
from pothole.cloud import validate_report
from pothole.storage import Store
from pothole.vision import Detector

CFG=json.loads((Path(__file__).resolve().parents[1]/'config/demo.json').read_text())


def record(x,y):
    lat,lon=to_gps(x,y,CFG['origin'])
    return {'id':'hazard','latitude':lat,'longitude':lon}


def warning(x,y,yaw=0,speed=3,steer=0,obstacle=(10,0)):
    return nearby_warning(x,y,yaw,speed,steer,[record(*obstacle)],CFG['origin'],CFG['warning'])


def test_warning_direction_lane_and_stationary():
    assert warning(0,0)
    assert warning(12,0) is None  # behind
    assert warning(0,4) is None  # another lane
    assert warning(0,0,math.pi) is None  # heading away
    assert warning(0,0,speed=0) is None
    assert warning(16,0,math.pi)  # approaching from opposite direction
    assert warning(0,0,obstacle=(35,0)) is None


def test_warning_follows_turn_instead_of_straight_cone():
    assert warning(0,0,steer=.55) is None
    k=math.tan(.55*.48)/1.16
    target=(math.sin(k*6)/k,(1-math.cos(k*6))/k)
    assert warning(0,0,steer=.55,obstacle=target)


def test_gps_interpolation_never_extrapolates_or_spans_dropouts():
    gps=GPSHistory()
    gps.add(1,-7,110)
    gps.add(1.2,-7.00002,110.00004)
    assert gps.interpolate(1.1)['longitude']==pytest.approx(110.00002)
    assert gps.interpolate(.9) is None
    assert gps.interpolate(1.3) is None
    gps.add(3,-7,110)
    assert gps.interpolate(2) is None


def test_gravity_compensation_when_tilted():
    pitch=.3
    q=SimpleNamespace(w=math.cos(pitch/2),x=0,y=math.sin(pitch/2),z=0)
    a=SimpleNamespace(x=-9.81*math.sin(pitch),y=0,z=9.81*math.cos(pitch))
    assert vertical_acceleration(a,q)==pytest.approx(0,abs=1e-9)


def test_imu_flat_road_impact_cooldown_and_reset():
    d=ImuDetector(CFG['imu'])
    rng=np.random.default_rng(2026)
    for i in range(350):
        assert not d.update(i*.01,float(rng.normal(0,.04)),0 if i<220 else 3)['triggered']
    hits=[]
    for i in range(150):
        z=-6 if i<12 else 12 if i<23 else 0
        if d.update(3.5+i*.01,z,3)['triggered']:
            hits.append(i)
    assert len(hits)==1
    d.reset()
    assert not d.update(4,30,3)['triggered']


def test_idempotent_sync_spatial_merge_and_durable_queue(tmp_path):
    device=Store(tmp_path/'device.db')
    cloud=Store(tmp_path/'cloud.db')
    r=device.add_report(dict(record(10,0),peak=8,source='imu'))
    assert len(Store(tmp_path/'device.db').pending())==1
    ids=cloud.receive([r]);cloud.receive([r])
    assert cloud.hazards()[0]['observations']==1
    r2=device.add_report(dict(record(10.5,0),peak=9,source='imu'))
    cloud.receive([r2])
    assert len(cloud.hazards())==1
    assert cloud.hazards()[0]['observations']==2
    device.mark_synced(ids)
    assert len(device.pending())==1
    device.replace_cache(cloud.hazards())
    assert len(device.cached())==1


def test_vision_reads_pixels():
    detector=Detector(CFG['vision'])
    empty=np.full((360,640,3),110,dtype=np.uint8)
    assert not detector.detect(empty)
    # Dark elliptical patch in the near-road ROI, without any world coordinates.
    import cv2
    cv2.ellipse(empty,(320,285),(47,19),0,0,360,(20,20,20),-1)
    found=detector.detect(empty)
    assert found and .6<found[0]['distance']<=3


def test_vision_rejects_thin_jagged_cracks():
    import cv2
    rgb=np.full((360,640,3),110,dtype=np.uint8)
    line=np.array([(x,260+int(12*math.sin(x/20))) for x in range(40,600)],np.int32)
    cv2.polylines(rgb,[line],False,(30,30,30),4)
    assert Detector(CFG['vision']).detect(rgb)==[]
    rgb[:]=110
    cv2.rectangle(rgb,(248,351),(293,359),(30,30,30),-1)
    assert Detector(CFG['vision']).detect(rgb)==[]


@pytest.mark.parametrize('pitch_sign,expected',[(1,True),(-1,False)])
def test_imu_pitch_rejects_bump_even_with_negative_acceleration_bias(pitch_sign,expected):
    detector=ImuDetector(CFG['imu'])
    hits=[]
    for i in range(500):
        dt=i*.01-3
        z=(-6 if dt<.12 else 12 if dt<.24 else 0) if dt>=0 else 0
        pitch=pitch_sign*.04 if 0<=dt<.4 else 0
        if detector.update(i*.01,z,3 if i>220 else 0,pitch)['triggered']:
            hits.append(i)
    assert bool(hits)==expected


def test_coordinates_roundtrip():
    lat,lon=to_gps(58,-2,CFG['origin'])
    assert to_xy(lat,lon,CFG['origin'])==pytest.approx((58,-2),abs=1e-7)


@pytest.mark.parametrize('surface',['bump','paving','crack'])
def test_imu_rejects_non_pothole_profiles(surface):
    d=ImuDetector(CFG['imu'])
    for i in range(600):
        t=i*.01
        z=0
        if t>=3:
            dt=t-3
            if surface=='bump' and dt<1:
                z=8*math.cos(2*math.pi*dt)
            elif surface=='paving':
                z=1.8*math.sin(dt*50)
            elif surface=='crack' and dt<.02:
                z=-2
        assert not d.update(t,z,3 if t>2.2 else 0)['triggered']


def test_reset_is_durable_and_backup_preserves_data(tmp_path):
    store=Store(tmp_path/'device.sqlite3')
    r=store.add_report(dict(record(10,0),peak=8,source='imu'))
    store.receive([r]);store.replace_cache(store.hazards())
    backup=store.backup()
    store.clear()
    reloaded=Store(tmp_path/'device.sqlite3')
    assert reloaded.counts()=={'total_reports':0,'pending':0,'cached':0}
    assert reloaded.hazards()==[]
    assert reloaded.get_meta('seed_initialized')=='1'
    old=Store(backup)
    assert len(old.pending())==len(old.hazards())==len(old.cached())==1


def test_server_rejects_vision_reports():
    with pytest.raises(ValueError):
        validate_report(dict(record(10,0),event_id='vision-report',peak=0,source='vision'))


def test_restart_after_reset_does_not_reseed(tmp_path):
    from pothole.cloud import initialize_demo
    path=tmp_path/'server.sqlite3'
    store=Store(path)
    initialize_demo(store,CFG,True)
    assert len(store.hazards())==1
    store.clear()
    store.db.close()
    restarted=Store(path)
    initialize_demo(restarted,CFG,True)
    assert restarted.hazards()==[]


def test_no_seed_first_start_stays_empty(tmp_path):
    from pothole.cloud import initialize_demo
    store=Store(tmp_path/'server.sqlite3')
    initialize_demo(store,CFG,False)
    initialize_demo(store,CFG,True)
    assert store.hazards()==[]


def test_stadium_closed_projection_and_paving_fraction():
    from pothole.track import length,point,project
    track=CFG['track'];total=length(track)
    assert total>500
    assert CFG['surfaces']['paving_length']/total<.5
    assert point(0,track)==pytest.approx(point(total,track))
    for s in np.linspace(0,total-.1,100):
        x,y,_=point(s,track,offset=-2)
        assert project(x,y,track)==pytest.approx(s,abs=1e-6)


@pytest.mark.parametrize('value',[float('nan'),float('inf'),None,'bad',True])
def test_server_rejects_invalid_coordinates(value):
    with pytest.raises(ValueError):
        validate_report({'event_id':'abc','latitude':value,'longitude':110,'peak':3})
