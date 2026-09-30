#!/usr/bin/env python3
"""One command starts the Gazebo world, device, local server, and dashboard."""
import argparse
import fcntl
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description='Simulasi capstone B-08')
    parser.add_argument('--gui',action='store_true',help='Buka juga antarmuka Gazebo; dashboard tetap tersedia')
    parser.add_argument('--headless',action='store_true',help='Gunakan EGL tanpa layar untuk rendering sensor')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--server-port',type=int,default=8766)
    parser.add_argument('--data-dir',default='data',help='Folder persistensi (gunakan folder baru untuk demo bersih)')
    parser.add_argument('--no-seed',action='store_true',help='Server mulai tanpa contoh lubang B')
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--duration',type=float,default=0,help='Hentikan setelah N detik, untuk pengujian')
    args=parser.parse_args()
    os.chdir(ROOT)
    data=Path(args.data_dir).resolve()
    data.mkdir(parents=True,exist_ok=True)
    logs=data/'logs'
    logs.mkdir(exist_ok=True)
    lock=(data/'run.lock').open('w')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error(f'Simulasi dengan folder {data} sudah berjalan.')
    for port in (args.port,args.server_port):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try:
                sock.bind(('127.0.0.1',port))
            except OSError:
                parser.error(f'Port {port} sedang digunakan; pilih --port dan --server-port lain.')
    if args.port==args.server_port:
        parser.error('Port dashboard dan server harus berbeda.')
    env=os.environ.copy()
    env['GZ_SIM_SYSTEM_PLUGIN_PATH']=str(ROOT/'build')+os.pathsep+env.get('GZ_SIM_SYSTEM_PLUGIN_PATH','')
    env['GZ_SIM_RESOURCE_PATH']=str(ROOT/'generated')+os.pathsep+env.get('GZ_SIM_RESOURCE_PATH','')
    env['GZ_PARTITION']=f'pothole-capstone-{args.port}'
    env['GZ_IP']='127.0.0.1'
    env['GZ_HOMEDIR']=str(data/'gazebo')
    env['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION']='python'
    env['PYTHONNOUSERSITE']='1'
    py='/usr/bin/python3'
    if not args.skip_build or not (ROOT/'build/libBicycleSystem.so').exists():
        subprocess.run(['cmake','-S',str(ROOT),'-B',str(ROOT/'build'),'-DCMAKE_BUILD_TYPE=Release'],env=env,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['cmake','--build',str(ROOT/'build'),'-j2'],env=env,check=True)
    # Always regenerate so a moved project has valid local asset URIs.
    subprocess.run([py,'-s','scripts/generate_world.py'],env=env,check=True)
    gz=['gz','sim','-r','-v','2']
    if not args.gui:
        gz+=['-s']
    if args.headless or not env.get('DISPLAY'):
        gz+=['--headless-rendering']
    gz+=[str(ROOT/'generated/capstone.sdf')]
    server=[py,'-s','-m','pothole.cloud','--port',str(args.server_port),'--data',str(data/'server.sqlite3')]
    if not args.no_seed:
        server+=['--seed-demo']
    device=[py,'-s','-m','pothole.web','--port',str(args.port),'--data',str(data/'device.sqlite3'),
            '--server',f'http://127.0.0.1:{args.server_port}']
    children=[]
    files=[]
    stopping=False
    def stop(signum=None,frame=None):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGINT,stop)
    signal.signal(signal.SIGTERM,stop)
    try:
        for name,cmd in [('server',server),('gazebo',gz),('device',device)]:
            output=(logs/f'{name}.log').open('w')
            files.append(output)
            proc=subprocess.Popen(cmd,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            children.append((name,proc))
        print(f'\nJAGA JALAN — Capstone B-08\nDashboard: http://localhost:{args.port}\n'
              f'Data: {data}\nLog: {logs}\n'
              'Buka dashboard di Firefox/Chrome, lalu klik Aktifkan suara.\n'
              'W/A/S/D + spasi atau stik PS. Ctrl+C untuk berhenti.\n',flush=True)
        started=time.monotonic()
        while not stopping and (not args.duration or time.monotonic()-started<args.duration):
            for name,proc in children:
                if proc.poll() is not None:
                    raise RuntimeError(f'{name} berhenti (kode {proc.returncode}). Lihat {logs}/{name}.log')
            time.sleep(.2)
    finally:
        # Signal only process groups created by this launcher.
        for _,proc in reversed(children):
            if proc.poll() is None:
                os.killpg(proc.pid,signal.SIGINT)
        for _,proc in reversed(children):
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGTERM)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGKILL)
        for f in files:
            f.close()
        print('Simulasi dihentikan. Database dan log tetap tersimpan.',flush=True)


if __name__=='__main__':
    try:
        main()
    except (RuntimeError,subprocess.CalledProcessError) as exc:
        print(str(exc),file=sys.stderr)
        sys.exit(1)
