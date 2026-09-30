import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .core import distance_m


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.lock=threading.RLock()
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS reports (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, synced INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS cache (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS hazards (id TEXT PRIMARY KEY, latitude REAL NOT NULL, longitude REAL NOT NULL, observations INTEGER NOT NULL, peak REAL NOT NULL, updated_at REAL NOT NULL, source TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS received (event_id TEXT PRIMARY KEY, hazard_id TEXT NOT NULL);
        ''')

    def add_report(self, report):
        report=dict(report,event_id=report.get('event_id',str(uuid.uuid4())))
        with self.lock,self.db:
            self.db.execute('INSERT OR IGNORE INTO reports(event_id,payload) VALUES(?,?)',
                            (report['event_id'],json.dumps(report)))
        return report

    def pending(self):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM reports WHERE synced=0 ORDER BY rowid LIMIT 100')]

    def mark_synced(self, ids):
        with self.lock,self.db:
            self.db.executemany('UPDATE reports SET synced=1 WHERE event_id=?',[(i,) for i in ids])

    def replace_cache(self, rows):
        with self.lock,self.db:
            self.db.execute('DELETE FROM cache')
            self.db.executemany('INSERT INTO cache VALUES(?,?)',[(r['id'],json.dumps(r)) for r in rows])

    def cached(self):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM cache')]

    def counts(self):
        with self.lock:
            total,pending=self.db.execute('SELECT count(*),coalesce(sum(1-synced),0) FROM reports').fetchone()
            return {'total_reports':total,'pending':pending,'cached':self.db.execute('SELECT count(*) FROM cache').fetchone()[0]}

    def hazards(self):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM hazards ORDER BY updated_at DESC')]

    def receive(self, reports, radius=2.5):
        accepted=[]
        with self.lock,self.db:
            for r in reports:
                if self.db.execute('SELECT 1 FROM received WHERE event_id=?',(r['event_id'],)).fetchone():
                    accepted.append(r['event_id'])
                    continue
                candidates=[h for h in self.hazards() if distance_m(h,r)<=radius]
                if candidates:
                    h=min(candidates,key=lambda h:distance_m(h,r))
                    n=h['observations']
                    self.db.execute('UPDATE hazards SET latitude=?,longitude=?,observations=?,peak=?,updated_at=? WHERE id=?',
                        ((h['latitude']*n+r['latitude'])/(n+1),(h['longitude']*n+r['longitude'])/(n+1),
                         n+1,max(h['peak'],r['peak']),time.time(),h['id']))
                    hazard_id=h['id']
                else:
                    hazard_id=str(uuid.uuid4())[:8]
                    self.db.execute('INSERT INTO hazards VALUES(?,?,?,?,?,?,?)',
                        (hazard_id,r['latitude'],r['longitude'],1,r['peak'],time.time(),r.get('source','imu')))
                self.db.execute('INSERT INTO received VALUES(?,?)',(r['event_id'],hazard_id))
                accepted.append(r['event_id'])
        return accepted
