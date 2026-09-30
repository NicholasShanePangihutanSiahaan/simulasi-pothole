#!/usr/bin/env python3
"""Generate local Gazebo assets. No Fuel downloads or internet during the show."""
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "generated"
ASSETS = OUT / "assets"
CFG = json.loads((ROOT / "config/demo.json").read_text())


def material(color):
    return f"<material><ambient>{color} 1</ambient><diffuse>{color} 1</diffuse><specular>0.05 0.05 0.05 1</specular></material>"


def box(name, xyz, size, color, collision=False):
    geom = f"<geometry><box><size>{' '.join(map(str, size))}</size></box></geometry>"
    pose = f"<pose>{' '.join(map(str, xyz))} 0 0 0</pose>"
    return (f'<visual name="{name}">{pose}{geom}{material(color)}</visual>' +
            (f'<collision name="{name}_collision">{pose}{geom}</collision>' if collision else ''))


def sphere(name, xyz, radius, color):
    return f'<visual name="{name}"><pose>{" ".join(map(str, xyz))} 0 0 0</pose><geometry><sphere><radius>{radius}</radius></sphere></geometry>{material(color)}</visual>'


def tube(name, start, end, radius, color):
    a, b = np.array(start), np.array(end)
    d = b-a
    length = np.linalg.norm(d)
    mid = (a+b)/2
    pitch = math.acos(d[2]/length)
    yaw = math.atan2(d[1], d[0])
    return f'<visual name="{name}"><pose>{mid[0]} {mid[1]} {mid[2]} 0 {pitch} {yaw}</pose><geometry><cylinder><radius>{radius}</radius><length>{length}</length></cylinder></geometry>{material(color)}</visual>'


def mesh(name, filename, collision=False):
    geom = f'<geometry><mesh><uri>{(ASSETS / filename).as_uri()}</uri></mesh></geometry>'
    return (f'<visual name="{name}">{geom}</visual>' +
            (f'<collision name="{name}_collision">{geom}<surface><friction><ode><mu>0.85</mu><mu2>0.85</mu2></ode></friction></surface></collision>' if collision else ''))


def collision_box(name, x0, x1, y0, y1):
    return f'<collision name="{name}"><pose>{(x0+x1)/2} {(y0+y1)/2} -.12 0 0 0</pose><geometry><box><size>{x1-x0} {y1-y0} .24</size></box></geometry></collision>'


def dae(path, points, faces, uv=None, texture=None, color="0.16 0.17 0.18 1"):
    # Mesh + UV data are reproducible procedural assets, not detector inputs.
    pts = np.asarray(points)
    uv = np.asarray(uv if uv is not None else pts[:, :2])
    face_array = np.asarray(faces)
    normals = np.zeros_like(pts, dtype=float)
    face_normals = np.cross(pts[face_array[:, 1]]-pts[face_array[:, 0]],
                            pts[face_array[:, 2]]-pts[face_array[:, 0]])
    for corner in range(3):
        np.add.at(normals, face_array[:, corner], face_normals)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    normal_values = ' '.join(f'{v:.6f}' for v in normals.flatten())
    indices = ' '.join(f'{i} {i} {i}' for face in faces for i in face)
    positions = ' '.join(f'{v:.5f}' for v in pts.flatten())
    uvs = ' '.join(f'{v:.5f}' for v in uv.flatten())
    tex = (f'<library_images><image id="tex"><init_from>{texture}</init_from></image></library_images>' if texture else '')
    params = ('<newparam sid="surface"><surface type="2D"><init_from>tex</init_from></surface></newparam><newparam sid="sampler"><sampler2D><source>surface</source></sampler2D></newparam>' if texture else '')
    diffuse = '<texture texture="sampler" texcoord="UV"/>' if texture else f'<color>{color}</color>'
    path.write_text(f'''<?xml version="1.0"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><unit meter="1" name="meter"/><up_axis>Z_UP</up_axis></asset>{tex}
<library_effects><effect id="effect"><profile_COMMON>{params}<technique sid="common"><phong><ambient><color>0.5 0.5 0.5 1</color></ambient><diffuse>{diffuse}</diffuse><specular><color>0.03 0.03 0.03 1</color></specular><shininess><float>4</float></shininess></phong></technique></profile_COMMON></effect></library_effects>
<library_materials><material id="mat"><instance_effect url="#effect"/></material></library_materials>
<library_geometries><geometry id="mesh"><mesh>
<source id="positions"><float_array id="pos-array" count="{pts.size}">{positions}</float_array><technique_common><accessor source="#pos-array" count="{len(pts)}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
<source id="uv"><float_array id="uv-array" count="{uv.size}">{uvs}</float_array><technique_common><accessor source="#uv-array" count="{len(uv)}" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>
<source id="normals"><float_array id="normal-array" count="{normals.size}">{normal_values}</float_array><technique_common><accessor source="#normal-array" count="{len(pts)}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
<vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
<triangles material="mat" count="{len(faces)}"><input semantic="VERTEX" source="#vertices" offset="0"/><input semantic="TEXCOORD" source="#uv" offset="1" set="0"/><input semantic="NORMAL" source="#normals" offset="2"/><p>{indices}</p></triangles>
</mesh></geometry></library_geometries><library_visual_scenes><visual_scene id="scene"><node id="road"><instance_geometry url="#mesh"><bind_material><technique_common><instance_material symbol="mat" target="#mat"><bind_vertex_input semantic="UV" input_semantic="TEXCOORD" input_set="0"/></instance_material></technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes><scene><instance_visual_scene url="#scene"/></scene></COLLADA>''')


def road_tile(label, x0, x1, hole=None):
    nx, ny = (61, 121) if hole else (2, 2)
    xs, ys = np.linspace(x0, x1, nx), np.linspace(-6, 6, ny)
    points, uvs = [], []
    def depression(x, y):
        if not hole:
            return np.zeros_like(x+y, dtype=float)
        dx, dy = (x-hole['x'])/hole['rx'], (y-hole['y'])/hole['ry']
        angle = np.arctan2(dy, dx)
        r = np.sqrt(dx*dx+dy*dy)/(1+.08*np.sin(5*angle)+.05*np.cos(9*angle))
        # Flatish bottom with steep, continuous eroded edges.
        return -hole['depth'] * np.clip((1-r)/.30, 0, 1)
    for y in ys:
        for x in xs:
            points.append((x, y, float(depression(x, y))))
            uvs.append(((x-x0)/(x1-x0), (y+6)/12))
    faces = []
    for j in range(ny-1):
        for i in range(nx-1):
            a = j*nx+i
            faces.extend([(a, a+1, a+nx), (a+1, a+nx+1, a+nx)])
    rng = np.random.default_rng(2026)
    n = 768
    xx, yy = np.meshgrid(np.linspace(x0,x1,n),np.linspace(6,-6,n))
    noise = rng.normal(0, 5, (n,n))
    depth = depression(xx, yy)
    grey = 107 + noise - np.clip(-depth*900, 0, 79)
    rgb = np.stack((grey*.94, grey*.97, grey), axis=-1).clip(0,255).astype('uint8')
    Image.fromarray(rgb).save(ASSETS/f'{label}.png')
    dae(ASSETS/f'{label}.dae', points, faces, uvs, f'{label}.png')
    result = mesh(label, f'{label}.dae')
    if not hole:
        return result+collision_box(label+'_flat',x0,x1,-6,6)
    # Keep flat adjacent lanes as primitive boxes. Dense coplanar mesh triangles
    # cause ODE contact chatter and spurious IMU spikes on an otherwise flat lane.
    y0,y1 = hole['y']-1.25,hole['y']+1.25
    collision_points=[]
    for y in np.linspace(y0,y1,41):
        for x in np.linspace(x0,x1,61):
            collision_points.append((x,y,float(depression(x,y))))
    collision_faces=[]
    for j in range(40):
        for i in range(60):
            a=j*61+i
            collision_faces.extend([(a,a+1,a+61),(a+1,a+62,a+61)])
    dae(ASSETS/f'{label}_contact.dae',collision_points,collision_faces)
    result += f'<collision name="{label}_depression"><geometry><mesh><uri>{(ASSETS / (label+"_contact.dae")).as_uri()}</uri></mesh></geometry></collision>'
    result += collision_box(label+'_lane_left',x0,x1,-6,y0)
    result += collision_box(label+'_lane_right',x0,x1,y1,6)
    return result


def tire_mesh():
    pts, faces = [], []
    for i in range(64):
        a = i*2*math.pi/64
        for j in range(12):
            b = j*2*math.pi/12
            r = .323+.027*math.cos(b)
            pts.append((r*math.cos(a), .027*math.sin(b), r*math.sin(a)))
    for i in range(64):
        for j in range(12):
            a,b = i*12+j, ((i+1)%64)*12+j
            c,d = i*12+(j+1)%12, ((i+1)%64)*12+(j+1)%12
            faces.extend([(a,c,b),(b,c,d)])
    dae(ASSETS/'tire.dae', pts, faces, color='0.035 0.041 0.044 1')


def inertia(mass, x, y, z):
    return f'<inertial><mass>{mass}</mass><inertia><ixx>{x}</ixx><iyy>{y}</iyy><izz>{z}</izz></inertia></inertial>'


def bicycle():
    teal, dark, silver = '0.02 0.62 0.52', '0.045 0.06 0.07', '0.5 0.58 0.6'
    # Coordinates relative to frame; model starts at z=.72, wheel centers at z=.35.
    rear, front, crank, seat, head = (-.58,0,-.37),(.58,0,-.37),(-.1,0,-.34),(-.32,0,.15),(.4,0,.14)
    frame = ''.join(tube(f'frame{i}', a,b,.028,teal) for i,(a,b) in enumerate(
        [(rear,crank),(rear,seat),(crank,seat),(seat,head),(head,crank)]))
    frame += tube('seatpost', seat,(-.32,0,.29),.023,silver)
    frame += box('saddle',(-.36,0,.30),(.27,.17,.05),dark)
    frame += tube('crank',(-.1,-.12,-.34),(-.1,.12,-.34),.03,silver)
    frame += box('pedal_left',(-.25,.18,-.34),(.12,.1,.03),dark)
    frame += box('pedal_right',(.05,-.18,-.34),(.12,.1,.03),dark)
    frame += box('device',(.44,0,.33),(.14,.14,.08),dark)
    frame += box('device_screen',(.44,0,.375),(.11,.10,.006),'0.1 0.9 0.7')
    # Seated rider silhouette, articulated segments; illustrative human geometry.
    frame += tube('rider_body',(-.31,0,.42),(.02,0,.89),.16,'0.94 0.40 0.13')
    frame += sphere('rider_head',(.10,0,1.10),.12,'0.64 0.42 0.29')
    frame += sphere('helmet',(.09,0,1.19),.145,'0.92 0.91 0.82')
    for side in (-1,1):
        s = str(side)
        frame += tube('upper_arm'+s,(.02,.15*side,.83),(.21,.22*side,.58),.052,'0.94 0.40 0.13')
        frame += tube('lower_arm'+s,(.21,.22*side,.58),(.45,.27*side,.29),.041,'0.64 0.42 0.29')
        frame += tube('thigh'+s,(-.31,.10*side,.40),(.04,.14*side,.03),.08,'0.075 0.105 0.15')
        frame += tube('shin'+s,(.04,.14*side,.03),(-.17,.17*side,-.30),.05,'0.64 0.42 0.29')
        frame += box('shoe'+s,(-.12,.17*side,-.30),(.24,.10,.08),dark)
    camera = '''<sensor name="road_camera" type="camera"><pose>.45 0 .36 0 .30 0</pose><topic>/capstone/camera</topic><update_rate>15</update_rate><always_on>true</always_on><camera><horizontal_fov>1.20</horizontal_fov><image><width>640</width><height>360</height><format>R8G8B8</format></image><clip><near>.08</near><far>180</far></clip></camera></sensor>
    <sensor name="chase_camera" type="camera"><pose>-4.5 0 2.60 0 .36 0</pose><topic>/capstone/chase</topic><update_rate>15</update_rate><always_on>true</always_on><camera><horizontal_fov>1.20</horizontal_fov><image><width>960</width><height>540</height><format>R8G8B8</format></image><clip><near>.1</near><far>180</far></clip></camera></sensor>'''
    imu = '<sensor name="imu" type="imu"><always_on>true</always_on><update_rate>100</update_rate><topic>/capstone/imu</topic><imu><linear_acceleration>'
    imu += ''.join(f'<{axis}><noise type="gaussian"><mean>0</mean><stddev>0.045</stddev></noise></{axis}>' for axis in 'xyz')
    imu += '</linear_acceleration></imu></sensor>'
    # Gazebo sensors8 applies horizontal noise in DEGREES (NavSatSensor.cc),
    # not metres: 3.15e-6 degree is approximately 0.35 m at this latitude.
    gps = '<sensor name="gps" type="navsat"><always_on>true</always_on><update_rate>5</update_rate><topic>/capstone/gps</topic><navsat><position_sensing><horizontal><noise type="gaussian"><mean>0</mean><stddev>0.00000315</stddev></noise></horizontal><vertical><noise type="gaussian"><mean>0</mean><stddev>0.6</stddev></noise></vertical></position_sensing></navsat></sensor>'
    result = '<model name="bicycle"><pose>4 -2 .72 0 0 0</pose><self_collide>false</self_collide>'
    result += '<link name="frame">'+inertia(82,9,14,14)+frame+camera+imu+gps+'</link>'
    fork = tube('fork_a',(.4,.04,.14),(.58,.04,-.37),.023,silver)+tube('fork_b',(.4,-.04,.14),(.58,-.04,-.37),.023,silver)
    fork += tube('handlebar',(.45,-.30,.29),(.45,.30,.29),.023,dark)
    fork += tube('stem',(.4,0,.14),(.45,0,.29),.028,silver)
    result += '<link name="fork">'+inertia(1,.08,.08,.08)+fork+'</link>'
    result += '<joint name="steering" type="revolute"><pose relative_to="frame">.4 0 .14 0 0 0</pose><parent>frame</parent><child>fork</child><axis><xyz>0 0 1</xyz><limit><lower>-.5</lower><upper>.5</upper><effort>250</effort></limit><dynamics><damping>.8</damping></dynamics></axis></joint>'
    for label, x, parent in [('rear',-.58,'frame'),('front',.58,'fork')]:
        visuals = mesh('tire','tire.dae')
        for i in range(16):
            a = i*math.pi/8
            visuals += tube(f'spoke{i}',(0,0,0),(.30*math.cos(a),0,.30*math.sin(a)),.0025,silver)
        visuals += tube('hub',(0,-.06,0),(0,.06,0),.026,silver)
        result += f'<link name="{label}_wheel"><pose>{x} 0 -.37 0 0 0</pose>'+inertia(1.2,.08,.15,.08)+visuals
        result += '<collision name="tire_contact"><pose>0 0 0 1.5707963 0 0</pose><geometry><cylinder><radius>.35</radius><length>.055</length></cylinder></geometry><surface><friction><ode><mu>.9</mu><mu2>.9</mu2></ode></friction></surface></collision></link>'
        result += f'<joint name="{label}_axle" type="revolute"><parent>{parent}</parent><child>{label}_wheel</child><axis><xyz>0 1 0</xyz><dynamics><damping>.015</damping></dynamics></axis></joint>'
    return result+'<plugin filename="BicycleSystem" name="capstone::BicycleSystem"/></model>'


def generate():
    ASSETS.mkdir(parents=True, exist_ok=True)
    tire_mesh()
    road = ''
    cursor = -8
    for hole in CFG['potholes']:
        x0, x1 = hole['x']-2, hole['x']+2
        road += road_tile('road_'+hole['name'], cursor,x0)
        road += road_tile('hole_'+hole['name'],x0,x1,hole)
        cursor = x1
    road += road_tile('road_end',cursor,155)
    road += box('ground',(72,0,-.40),(200,140,.25),'0.28 0.40 0.20',True)
    for y in (-6.7,6.7):
        road += box('sidewalk'+str(y),(73,y,.04),(166,1.35,.12),'0.57 0.58 0.54',True)
        road += box('edge'+str(y),(73,math.copysign(5.8,y),.004),(166,.10,.008),'0.86 0.86 0.77')
    for i,x in enumerate(range(-5,154,6)):
        road += box('dash'+str(i),(x,0,.005),(2.8,.10,.01),'0.94 0.83 0.42')
    scenery = ''
    rng = np.random.default_rng(17)
    for i,x in enumerate(range(-4,153,12)):
        for side in (-1,1):
            y = side*9.5
            name = f'{i}_{side}'
            scenery += tube('trunk'+name,(x,y,-.2),(x,y,3.8),.19,'0.28 0.19 0.12')
            scenery += sphere('crown'+name,(x,y,4.2),1.8,'0.15 0.34 0.15')
            scenery += sphere('crown2'+name,(x+.8,y,5),1.25,'0.22 0.43 0.19')
            if i%2==0:
                lx,ly=x+4,side*7.5
                scenery += tube('pole'+name,(lx,ly,0),(lx,ly,5.5),.055,'0.21 0.25 0.27')
                scenery += tube('arm'+name,(lx,ly,5.5),(lx,ly-side*1,5.7),.05,'0.21 0.25 0.27')
                scenery += box('lamp'+name,(lx,ly-side*1,5.7),(.6,.25,.09),'0.82 0.85 0.79')
            h=float(rng.uniform(5,10))
            color=['0.68 0.67 0.59','0.66 0.53 0.42','0.66 0.71 0.70'][i%3]
            scenery += box('building'+name,(x,side*18,h/2-.2),(8,9,h),color)
            scenery += box('roof'+name,(x,side*18,h-.1),(8.4,9.4,.28),'0.31 0.24 0.21')
            for wx in (-2.5,0,2.5):
                for level in range(1,int(h/2)):
                    scenery += box(f'window{name}_{wx}_{level}',(x+wx,side*13.48,level*2),(1.15,.04,1.1),'0.20 0.34 0.39')
    origin=CFG['origin']
    plugins=''.join(f'<plugin filename="gz-sim-{file}-system" name="gz::sim::systems::{name}"/>' for file,name in [('physics','Physics'),('user-commands','UserCommands'),('scene-broadcaster','SceneBroadcaster'),('imu','Imu'),('navsat','NavSat')])
    text=f'''<?xml version="1.0"?><sdf version="1.9"><world name="capstone">
    <physics name="physics" type="ignored"><max_step_size>0.002</max_step_size><real_time_factor>1</real_time_factor></physics>
    <gravity>0 0 -9.81</gravity>{plugins}
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors"><render_engine>ogre2</render_engine></plugin>
    <spherical_coordinates><surface_model>EARTH_WGS84</surface_model><world_frame_orientation>ENU</world_frame_orientation><latitude_deg>{origin['latitude']}</latitude_deg><longitude_deg>{origin['longitude']}</longitude_deg><elevation>{origin['altitude']}</elevation><heading_deg>0</heading_deg></spherical_coordinates>
    <scene><ambient>.7 .7 .7 1</ambient><background>.62 .77 .87 1</background><shadows>true</shadows><grid>false</grid></scene>
    <light type="directional" name="sun"><pose>0 0 30 0 0 0</pose><diffuse>.95 .91 .82 1</diffuse><specular>.15 .15 .15 1</specular><direction>-.4 -.2 -1</direction><cast_shadows>true</cast_shadows></light>
    <gui fullscreen="false"><plugin filename="MinimalScene" name="3D View"><gz-gui><title>Lintasan Capstone B-08</title><property type="bool" key="showTitleBar">false</property><property type="string" key="state">docked</property></gz-gui><engine>ogre2</engine><scene>scene</scene><ambient_light>.7 .7 .7</ambient_light><background_color>.62 .77 .87</background_color><camera_pose>-4 -10 7 0 .35 .55</camera_pose></plugin><plugin filename="GzSceneManager" name="Scene Manager"/><plugin filename="InteractiveViewControl" name="View Control"/><plugin filename="CameraTracking" name="Camera Tracking"/><plugin filename="WorldControl" name="World Control"><gz-gui><property type="string" key="state">floating</property></gz-gui><start_paused>false</start_paused></plugin></gui>
    <model name="road"><static>true</static><link name="surface">{road}</link></model>
    <model name="campus"><static>true</static><link name="scenery">{scenery}</link></model>
    {bicycle()}</world></sdf>'''
    ET.fromstring(text)
    (OUT/'capstone.sdf').write_text(text)
    print(f'World siap: {OUT / "capstone.sdf"}')


if __name__ == '__main__':
    generate()
