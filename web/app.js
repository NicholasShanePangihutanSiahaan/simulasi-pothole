'use strict';
const $ = id => document.getElementById(id);
let state=null, sound=null, soundOn=false, lastBeep=0, mainView='chase', focused=true;
const keys=new Set(), touch=new Set();
let toastTimer, previousGameButtons=[], gamepadName='';
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3500);}
async function post(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(!r.ok){const e=await r.json();throw new Error(e.error||'Permintaan gagal');}return r.json();}
function safely(p){p.catch(e=>toast(e.message));}
function enableSound(){if(!sound)sound=new (window.AudioContext||window.webkitAudioContext)();sound.resume();soundOn=!soundOn;$('sound').textContent=soundOn?'♬ Suara aktif':'♬ Aktifkan suara';$('sound').classList.toggle('active',soundOn);if(soundOn)beep(true);}
function beep(test=false){if(!soundOn||!sound||sound.state!=='running')return;const now=sound.currentTime;if(!test&&now-lastBeep<.34)return;lastBeep=now;const o=sound.createOscillator(),g=sound.createGain();o.type='sine';o.frequency.value=state?.buzzer.sources.includes('VISION')?1080:780;g.gain.setValueAtTime(0,now);g.gain.linearRampToValueAtTime(.12,now+.01);g.gain.setValueAtTime(.12,now+.10);g.gain.linearRampToValueAtTime(0,now+.14);o.connect(g);g.connect(sound.destination);o.start(now);o.stop(now+.15);}
$('sound').onclick=enableSound;
$('fullscreen').onclick=()=>safely(document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen());
$('cameraSwitch').onclick=()=>{mainView=mainView==='chase'?'camera':'chase';$('mainCamera').src='/stream/'+mainView;};
$('auto').onclick=()=>safely(post('/api/options',{autopilot:!state?.options.autopilot}));
function reset(scenario){safely(post('/api/reset',{scenario}));keys.clear();touch.clear();toast('Posisi dipindahkan. Tunggu kalibrasi IMU 2 detik.');}
$('reset').onclick=()=>reset($('scenario').value);
for(const option of ['vision','imu','database','online','fusion'])$('opt-'+option).onchange=e=>safely(post('/api/options',{[option]:e.target.checked}));
const driveKeys=new Set(['w','a','s','d','arrowup','arrowdown','arrowleft','arrowright',' ']);
window.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA','BUTTON','SUMMARY'].includes(e.target.tagName))return;const k=e.key.toLowerCase();if(driveKeys.has(k)){e.preventDefault();keys.add(k);if(e.shiftKey)keys.add('shift');}if(!e.repeat&&k==='r')reset('start');if(!e.repeat&&k==='p')$('auto').click();});
window.addEventListener('keyup',e=>{keys.delete(e.key.toLowerCase());if(!e.shiftKey)keys.delete('shift');});
function stopInput(){keys.clear();touch.clear();focused=false;safely(post('/api/control',{throttle:0,steer:0,brake:1}));}
window.addEventListener('blur',stopInput);window.addEventListener('focus',()=>focused=true);
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopInput();else focused=true;});
window.addEventListener('gamepaddisconnected',()=>{previousGameButtons=[];stopInput();focused=document.hasFocus();toast('Stik terputus. Sepeda direm.');});
for(const b of document.querySelectorAll('[data-drive]')){b.onpointerdown=e=>{e.preventDefault();b.setPointerCapture(e.pointerId);touch.add(b.dataset.drive);};b.onpointerup=b.onpointercancel=()=>touch.delete(b.dataset.drive);}
let sending=false;
setInterval(async()=>{
  if(sending||!state)return;
  let throttle=0,steer=0,brake=0,hasInput=false;
  if(focused){
    throttle=keys.has('w')||keys.has('arrowup')||touch.has('forward')?1:0;
    if(keys.has('s')||keys.has('arrowdown')){if(keys.has('shift'))throttle=-.55;else brake=.8;}
    steer=(keys.has('a')||keys.has('arrowleft')||touch.has('left')?1:0)-(keys.has('d')||keys.has('arrowright')||touch.has('right')?1:0);
    if(keys.has(' ')||touch.has('brake'))brake=1;
    hasInput=throttle!==0||steer!==0||brake!==0;
    const pad=Array.from(navigator.getGamepads?.()||[]).find(p=>p?.connected);
    if(pad){
      gamepadName=pad.id;const axis=pad.axes[0]||0;
      const ps=-(Math.abs(axis)<.12?0:Math.sign(axis)*(Math.abs(axis)-.12)/.88)*($('invertSteer').checked?-1:1);
      const pt=pad.buttons[7]?.value||0,pb=Math.max(pad.buttons[6]?.value||0,pad.buttons[0]?.value||0);
      if(Math.abs(ps)>.04||pt>.04||pb>.04){steer=ps;throttle=pt;brake=pb;hasInput=true;}
      if(pad.buttons[3]?.pressed&&!previousGameButtons[3])reset('start');
      if(pad.buttons[9]?.pressed&&!previousGameButtons[9])$('auto').click();
      previousGameButtons=pad.buttons.map(b=>b.pressed);
      $('controller').textContent='◉ STIK PS / GAMEPAD';$('controller').title=gamepadName;
    }else{$('controller').textContent='⌨ KEYBOARD';}
  }
  // Autopilot owns commands only while no person is using the controls.
  if(state.options.autopilot&&!hasInput&&focused){sending=true;try{await post('/api/heartbeat',{});}catch(e){}finally{sending=false;}return;}
  if(!focused){throttle=steer=0;brake=1;}
  sending=true;try{await post('/api/control',{throttle,steer,brake});}catch(e){/* state polling reports connectivity */}finally{sending=false;}
},100);
function fit(canvas){const d=window.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;if(canvas.width!==w*d||canvas.height!==h*d){canvas.width=w*d;canvas.height=h*d;}const c=canvas.getContext('2d');c.setTransform(d,0,0,d,0,0);c.clearRect(0,0,w,h);return {c,w,h};}
function drawChart(s){const {c,w,h}=fit($('chart'));const data=s.imu_history;const max=Math.max(7,...data.map(p=>Math.abs(p[1])))*1.1;const y=v=>h/2-v/max*(h/2-9);c.strokeStyle='#33453e';c.lineWidth=.7;for(const v of [-max/2,0,max/2]){c.beginPath();c.moveTo(0,y(v));c.lineTo(w,y(v));c.stroke();}c.setLineDash([3,4]);c.strokeStyle='#967844';for(const v of [-s.config.imu.z_threshold,s.config.imu.z_threshold]){c.beginPath();c.moveTo(0,y(v));c.lineTo(w,y(v));c.stroke();}c.setLineDash([]);if(data.length>1){const t=data[data.length-1][0],span=4.5;c.beginPath();let started=false;for(const p of data){const x=w-(t-p[0])/span*w;if(x<0)continue;if(!started){c.moveTo(x,y(p[1]));started=true;}else c.lineTo(x,y(p[1]));}c.strokeStyle='#83d2b3';c.lineWidth=1.6;c.stroke();}c.fillStyle='#7f9b8c';c.font='8px monospace';c.fillText('+'+max.toFixed(0),5,10);c.fillText('−'+max.toFixed(0),5,h-3);}
function drawMap(s){const {c,w,h}=fit($('map'));const mx=x=>15+(x+2)/148*(w-30),my=y=>h/2-y*4;for(let x=0;x<w;x+=20){c.strokeStyle='#23332b';c.beginPath();c.moveTo(x,0);c.lineTo(x,h);c.stroke();}c.fillStyle='#33453d';c.fillRect(mx(0),my(5.7),mx(144)-mx(0),45.6);c.strokeStyle='#83916f';c.setLineDash([6,6]);c.beginPath();c.moveTo(mx(0),my(0));c.lineTo(mx(144),my(0));c.stroke();c.setLineDash([]);c.fillStyle='#70877a';c.font='7px monospace';for(let x=0;x<=140;x+=20)c.fillText(x+'m',mx(x)-6,h-6);for(const p of s.potholes){const x=(p.longitude-s.config.origin.longitude)*Math.PI/180*6378137*Math.cos(s.config.origin.latitude*Math.PI/180),y=(p.latitude-s.config.origin.latitude)*Math.PI/180*6378137;c.fillStyle='#f5b75a22';c.beginPath();c.arc(mx(x),my(y),9,0,Math.PI*2);c.fill();c.fillStyle='#f5b75a';c.beginPath();c.arc(mx(x),my(y),3.5,0,Math.PI*2);c.fill();}c.save();c.translate(mx(s.pose.x),my(s.pose.y));c.rotate(-s.pose.yaw);c.fillStyle='#9be7c4';c.beginPath();c.moveTo(7,0);c.lineTo(-5,-4);c.lineTo(-3,0);c.lineTo(-5,4);c.closePath();c.fill();c.restore();}
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let lastEventKey='';
function render(s){
  const healthy=s.health.gazebo;
  $('connection').textContent=healthy?'SIMULASI AKTIF':'MENUNGGU GAZEBO';$('liveDot').classList.toggle('ready',healthy);
  $('cameraWaiting').hidden=s.health.camera;
  $('speed').textContent=Math.abs(s.pose.speed*3.6).toFixed(1);$('motion').textContent=s.options.autopilot?'DEMO OTOMATIS':s.pose.speed<-.2?'MUNDUR':s.pose.speed>.2?'BERKENDARA':'BERHENTI';
  const heading=(90-s.pose.yaw*180/Math.PI+360)%360;
  $('heading').textContent='ARAH '+heading.toFixed(0).padStart(3,'0')+'° · '+['UTARA','TIMUR','SELATAN','BARAT'][Math.round(heading/90)%4];
  $('gpsText').textContent=s.gps?s.gps.latitude.toFixed(6)+' / '+s.gps.longitude.toFixed(6):'GPS · menunggu posisi';
  $('progress').style.width=Math.max(0,Math.min(100,s.pose.x/144*100))+'%';
  $('fps').textContent=s.vision.fps.toFixed(1)+' FPS';$('latency').textContent=s.vision.latency_ms.toFixed(1)+' ms / frame';
  $('visionFlag').textContent=!s.options.vision?'VISION NONAKTIF':s.vision.detections.length?'DUGAAN LUBANG TERDETEKSI':'TIDAK ADA DETEKSI';$('visionFlag').classList.toggle('warn',s.vision.detections.length>0);
  $('az').textContent=s.imu.z.toFixed(2);$('imuFlag').textContent=s.imu.calibrating?'KALIBRASI':s.imu.triggered?'ANOMALI':'MEMANTAU';$('std').textContent='σ '+s.imu.std.toFixed(2)+' · ΔZ '+s.imu.diff.toFixed(2);
  const warn=s.buzzer.active;
  $('alertPanel').classList.toggle('warning',warn);$('alertSymbol').textContent=warn?'!':'✓';
  $('alertTitle').textContent=warn?'Waspada jalan rusak':healthy?'Tidak ada peringatan':'Menunggu sensor';
  $('alertDetail').textContent=warn?s.buzzer.sources.join(' + ')+(s.db_warning?' · '+s.db_warning.distance.toFixed(1)+' m di depan':' · terdeteksi pada kamera'):s.imu.calibrating?'Kalibrasi IMU; sepeda ditahan selama 2 detik.':!soundOn?'Suara nonaktif · klik Aktifkan suara.':'Kamera dan cache lokasi sedang dipantau.';
  $('roadAlert').hidden=!warn;$('roadAlertSub').textContent=s.buzzer.sources.join(' + ')+(s.db_warning?' · estimasi '+s.db_warning.eta.toFixed(1)+' detik':' · kamera depan');
  if(warn)beep();
  $('cacheCount').textContent=s.storage.cached+' TITIK';$('reports').textContent=s.storage.total_reports;$('pending').textContent=s.storage.pending;
  $('syncStatus').textContent=!s.options.online?'● Offline · cache tetap aktif':s.sync.error?'● Server belum tersambung':'● Sinkron · '+s.sync.ms.toFixed(0)+' ms';
  for(const option of ['vision','imu','database','online','fusion']){const input=$('opt-'+option);if(document.activeElement!==input)input.checked=s.options[option];}
  $('auto').classList.toggle('active',s.options.autopilot);$('auto').textContent=s.options.autopilot?'Ⅱ Hentikan demo':'▷ Demo otomatis';
  $('health').textContent=Object.entries(s.health).map(([k,v])=>k.toUpperCase()+' '+(v?'●':'○')).join('  ');
  const key=s.events[0]?.wall+':'+s.events.length;
  if(key!==lastEventKey){lastEventKey=key;$('events').innerHTML=s.events.map(e=>`<div class="event ${esc(e.level)}"><time>${esc(e.time)}</time><div><strong>${esc(e.kind)}</strong><p>${esc(e.message)}</p></div></div>`).join('');}
  drawChart(s);drawMap(s);
}
async function poll(){try{const r=await fetch('/api/state');if(!r.ok)throw Error('server');state=await r.json();render(state);}catch(e){$('connection').textContent='DASHBOARD TERPUTUS';$('liveDot').classList.remove('ready');$('alertTitle').textContent='Koneksi terputus';$('alertDetail').textContent='Periksa terminal launcher. Sepeda direm otomatis.';}setTimeout(poll,150);}
setInterval(()=>$('clock').textContent=new Date().toLocaleTimeString('id-ID',{hour12:false}).replaceAll('.',':'),1000);
poll();
