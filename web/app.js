'use strict';
const $ = id => document.getElementById(id);
let state=null, sound=null, soundOn=false, lastBeep=0, mainView='chase', focused=true;
const keys=new Set(), touch=new Set();
let toastTimer, previousGameButtons=[], gamepadName='', smoothSteer=0;
const steeringDefaults={sensitivity:55,response:45};
function savedNumber(key,fallback){const value=Number(localStorage.getItem(key));return Number.isFinite(value)?value:fallback;}
function steeringSettings(){return {sensitivity:Number($('steerSensitivity').value)/100,response:Number($('steerResponse').value)/100};}
function responseLabel(value){return value<.34?'Halus':value<.67?'Sedang':'Cepat';}
function showSteeringSettings(){const s=steeringSettings();$('steerSensitivityValue').textContent=Math.round(s.sensitivity*100)+'% · '+(27.5*s.sensitivity).toFixed(0)+'°';$('steerResponseValue').textContent=responseLabel(s.response);}
$('steerSensitivity').value=Math.max(20,Math.min(100,savedNumber('pothole-steer-sensitivity',steeringDefaults.sensitivity)));
$('steerResponse').value=Math.max(10,Math.min(100,savedNumber('pothole-steer-response',steeringDefaults.response)));
for(const id of ['steerSensitivity','steerResponse'])$(id).oninput=()=>{localStorage.setItem('pothole-'+(id==='steerSensitivity'?'steer-sensitivity':'steer-response'),$(id).value);showSteeringSettings();};
$('resetSteering').onclick=()=>{$('steerSensitivity').value=steeringDefaults.sensitivity;$('steerResponse').value=steeringDefaults.response;localStorage.setItem('pothole-steer-sensitivity',steeringDefaults.sensitivity);localStorage.setItem('pothole-steer-response',steeringDefaults.response);showSteeringSettings();toast('Setelan kemudi kembali ke standar.');};
showSteeringSettings();
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3500);}
async function post(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(!r.ok){const e=await r.json();throw new Error(e.error||'Permintaan gagal');}return r.json();}
function safely(p){p.catch(e=>toast(e.message));}
function enableSound(){if(!sound)sound=new (window.AudioContext||window.webkitAudioContext)();sound.resume();soundOn=!soundOn;$('sound').textContent=soundOn?'♬ Suara aktif':'♬ Aktifkan suara';$('sound').classList.toggle('active',soundOn);if(soundOn)beep(true);}
function beep(test=false){if(!soundOn||!sound||sound.state!=='running')return;const now=sound.currentTime;if(!test&&now-lastBeep<.34)return;lastBeep=now;const o=sound.createOscillator(),g=sound.createGain();o.type='sine';o.frequency.value=state?.buzzer.sources.includes('VISION')?1080:780;g.gain.setValueAtTime(0,now);g.gain.linearRampToValueAtTime(.12,now+.01);g.gain.setValueAtTime(.12,now+.10);g.gain.linearRampToValueAtTime(0,now+.14);o.connect(g);g.connect(sound.destination);o.start(now);o.stop(now+.15);}
$('sound').onclick=enableSound;
$('fullscreen').onclick=()=>safely(document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen());
$('cameraSwitch').onclick=()=>{mainView=mainView==='chase'?'camera':'chase';$('mainCamera').src='/stream/'+mainView;};
$('auto').onclick=()=>safely(post('/api/options',{autopilot:!state?.options.autopilot}));
function reset(scenario){safely(post('/api/reset',{scenario}));keys.clear();touch.clear();smoothSteer=0;toast('Posisi dipindahkan. Tunggu kalibrasi IMU 2 detik.');}
$('reset').onclick=()=>reset($('scenario').value);
for(const [value,label] of [['small','C · Pothole kecil / lajur kiri'],['crack','Retakan · bukan pothole'],['bump','Polisi tidur · bukan pothole'],['paving','Paving blok · 60 m'],['curve','Tikungan arena oval']])$('scenario').add(new Option(label,value));
$('resetDatabase').onclick=async()=>{
  stopInput();
  if(!confirm('Reset semua temuan pothole?\nDatabase server, cache, dan antrean IMU akan dikosongkan. Lubang fisik tetap ada untuk ditemukan ulang. Cadangan otomatis disimpan.')){focused=document.hasFocus();return;}
  const button=$('resetDatabase');button.disabled=true;
  try{await post('/api/database/reset',{confirm:'RESET POTHOLE DATABASE'});toast('Database kosong. Tunggu kalibrasi 2 detik, lalu temukan pothole kembali.');}
  catch(e){toast(e.message);}finally{button.disabled=false;focused=document.hasFocus();}
};
for(const option of ['vision','imu','database','online'])$('opt-'+option).onchange=e=>safely(post('/api/options',{[option]:e.target.checked}));
const driveKeys=new Set(['w','a','s','d','arrowup','arrowdown','arrowleft','arrowright',' ']);
window.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA','BUTTON','SUMMARY'].includes(e.target.tagName))return;const k=e.key.toLowerCase();if(driveKeys.has(k)){e.preventDefault();keys.add(k);if(e.shiftKey)keys.add('shift');}if(!e.repeat&&k==='r')reset('start');if(!e.repeat&&k==='p')$('auto').click();});
window.addEventListener('keyup',e=>{keys.delete(e.key.toLowerCase());if(!e.shiftKey)keys.delete('shift');});
function stopInput(){keys.clear();touch.clear();smoothSteer=0;focused=false;safely(post('/api/control',{throttle:0,steer:0,brake:1}));}
window.addEventListener('blur',stopInput);window.addEventListener('focus',()=>focused=true);
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopInput();else focused=true;});
window.addEventListener('gamepaddisconnected',()=>{previousGameButtons=[];stopInput();focused=document.hasFocus();toast('Stik terputus. Sepeda direm.');});
for(const b of document.querySelectorAll('[data-drive]')){b.onpointerdown=e=>{e.preventDefault();b.setPointerCapture(e.pointerId);touch.add(b.dataset.drive);};b.onpointerup=b.onpointercancel=()=>touch.delete(b.dataset.drive);}
let sending=false;
setInterval(async()=>{
  if(sending||!state)return;
  let throttle=0,targetSteer=0,brake=0,hasInput=false;
  if(focused){
    const settings=steeringSettings();
    throttle=keys.has('w')||keys.has('arrowup')||touch.has('forward')?1:0;
    if(keys.has('s')||keys.has('arrowdown')){if(keys.has('shift'))throttle=-.55;else brake=.8;}
    targetSteer=((keys.has('a')||keys.has('arrowleft')||touch.has('left')?1:0)-(keys.has('d')||keys.has('arrowright')||touch.has('right')?1:0))*settings.sensitivity;
    if(keys.has(' ')||touch.has('brake'))brake=1;
    hasInput=throttle!==0||targetSteer!==0||brake!==0;
    const pad=Array.from(navigator.getGamepads?.()||[]).find(p=>p?.connected);
    if(pad){
      gamepadName=pad.id;const axis=pad.axes[0]||0;
      const normalized=Math.abs(axis)<.12?0:Math.sign(axis)*(Math.abs(axis)-.12)/.88;
      const ps=-Math.sign(normalized)*Math.pow(Math.abs(normalized),1.6)*settings.sensitivity*($('invertSteer').checked?-1:1);
      const pt=pad.buttons[7]?.value||0,pb=Math.max(pad.buttons[6]?.value||0,pad.buttons[0]?.value||0);
      if(Math.abs(ps)>.02||pt>.04||pb>.04){targetSteer=ps;throttle=pt;brake=pb;hasInput=true;}
      if(pad.buttons[3]?.pressed&&!previousGameButtons[3])reset('start');
      if(pad.buttons[9]?.pressed&&!previousGameButtons[9])$('auto').click();
      previousGameButtons=pad.buttons.map(b=>b.pressed);
      $('controller').textContent='◉ STIK PS / GAMEPAD';$('controller').title=gamepadName;
    }else{$('controller').textContent='⌨ KEYBOARD';}
  }
  // Autopilot owns commands only while no person is using the controls.
  if(state.options.autopilot&&!hasInput&&focused){sending=true;try{await post('/api/heartbeat',{});}catch(e){}finally{sending=false;}return;}
  if(!focused){throttle=targetSteer=0;brake=1;}
  const response=steeringSettings().response;
  const maxStep=.035+.315*response;
  smoothSteer+=Math.max(-maxStep,Math.min(maxStep,targetSteer-smoothSteer));
  if(Math.abs(smoothSteer)<.004&&targetSteer===0)smoothSteer=0;
  sending=true;try{await post('/api/control',{throttle,steer:smoothSteer,brake});}catch(e){/* state polling reports connectivity */}finally{sending=false;}
},100);
function fit(canvas){const d=window.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;if(canvas.width!==w*d||canvas.height!==h*d){canvas.width=w*d;canvas.height=h*d;}const c=canvas.getContext('2d');c.setTransform(d,0,0,d,0,0);c.clearRect(0,0,w,h);return {c,w,h};}
function drawChart(s){
  const {c,w,h}=fit($('chart')),span=4.5,t=s.imu_history.at(-1)?.[0]||0;
  const data=s.imu_history.filter(p=>p[0]>=t-span),threshold=s.config.imu.z_threshold;
  const max=Math.max(7,threshold*1.2,...data.map(p=>Math.abs(p[1])))*1.1;
  const y=v=>h/2-v/max*(h/2-12),x=p=>w-(t-p[0])/span*w;
  c.strokeStyle='#33453e';c.lineWidth=.7;
  for(const v of [-max/2,0,max/2]){c.beginPath();c.moveTo(0,y(v));c.lineTo(w,y(v));c.stroke();}
  c.setLineDash([3,4]);c.strokeStyle='#b89553';
  for(const v of [-threshold,threshold]){c.beginPath();c.moveTo(0,y(v));c.lineTo(w,y(v));c.stroke();}
  c.setLineDash([]);
  if(data.length>1){c.beginPath();data.forEach((p,i)=>i?c.lineTo(x(p),y(p[1])):c.moveTo(x(p),y(p[1])));c.strokeStyle='#83d2b3';c.lineWidth=1.6;c.stroke();}
  for(const p of data)if(p[2]==='pothole'){c.fillStyle='#f5b75a';c.beginPath();c.arc(x(p),y(p[1]),3.5,0,2*Math.PI);c.fill();}
  c.font='8px monospace';c.fillStyle='#b89553';c.textAlign='right';c.fillText('±'+threshold.toFixed(1)+' m/s²',w-5,10);
  c.textAlign='left';c.fillStyle='#7f9b8c';c.fillText('+'+max.toFixed(1),5,10);c.fillText('−'+max.toFixed(1),5,h-3);c.textAlign='right';c.fillText('4,5 dtk · skala Y otomatis',w-5,h-3);c.textAlign='left';
}
function renderImu(s){
  const imu=s.imu,a=imu.assessment,threshold=s.config.imu.z_threshold;
  const recent=imu.last_detection&&s.pose.time-imu.last_detection.time>=0&&s.pose.time-imu.last_detection.time<1.5;
  $('az').textContent=imu.z.toFixed(2);
  $('imuFlag').textContent=!s.options.imu?'IMU NONAKTIF':imu.calibrating?'KALIBRASI':recent?'POTHOLE':imu.classification==='bump/rejected'?'TONJOLAN DITOLAK':imu.classification==='candidate'?'UJI POLA':'MEMANTAU';
  $('imuThreshold').textContent='±'+threshold.toFixed(1)+' · syarat puncak';
  $('std').textContent='σ '+imu.std.toFixed(2)+' · ΔZ '+imu.diff.toFixed(2)+' (info)';
  let detail='Belum ada pola pothole. Guncangan besar juga dapat berasal dari paving atau polisi tidur.';
  if(!s.options.imu)detail='Pencatatan IMU nonaktif; grafik sensor tetap berjalan.';
  else if(imu.calibrating)detail='Kalibrasi bias IMU; tahan sepeda tetap diam selama 2 detik.';
  else if(recent)detail='Pola pothole terkonfirmasi · puncak kejadian '+imu.last_detection.peak.toFixed(2)+' m/s². Proses pencatatan lokasi dipicu.';
  else if(a){
    const peak='Puncak kejadian '+a.peak.toFixed(2)+' / '+threshold.toFixed(1)+' m/s². ';
    detail=peak+(a.first_motion==='rise'?'Ditolak: bagian depan naik terlebih dahulu (pola tonjolan).':a.checks.amplitude?'Syarat amplitudo terpenuhi; pola turun dan benturan belum lengkap.':'Syarat amplitudo belum terpenuhi; guncangan masih dipantau.');
  }
  $('imuDecision').textContent=detail;
}
function drawMap(s){
  const {c,w,h}=fit($('map')),t=s.config.track,r=t.radius,l=t.straight;
  const scale=Math.min((w-30)/(l+2*r+16),(h-35)/(2*r+16));
  const mx=x=>w/2+(x-l/2)*scale,my=y=>h/2-(y-r)*scale;
  function stadium(){c.beginPath();c.moveTo(mx(0),my(0));c.lineTo(mx(l),my(0));c.arc(mx(l),my(r),r*scale,Math.PI/2,-Math.PI/2,true);c.lineTo(mx(0),my(2*r));c.arc(mx(0),my(r),r*scale,-Math.PI/2,Math.PI/2,true);c.closePath();}
  stadium();c.strokeStyle='#43534c';c.lineWidth=t.width*scale;c.stroke();
  stadium();c.strokeStyle='#9b9b71';c.lineWidth=.7;c.setLineDash([3,4]);c.stroke();c.setLineDash([]);
  const surface=s.config.surfaces;
  c.strokeStyle='#b3a28b';c.lineWidth=t.width*scale;c.beginPath();c.moveTo(mx(l-surface.paving_start),my(2*r));c.lineTo(mx(l-surface.paving_start-surface.paving_length),my(2*r));c.stroke();
  c.strokeStyle='#f0c35e';c.lineWidth=3;c.beginPath();c.moveTo(mx(surface.bump_x),my(-5));c.lineTo(mx(surface.bump_x),my(5));c.stroke();
  c.fillStyle='#a8b9ac';c.font='8px monospace';c.textAlign='center';c.fillText('PAVING 60 m',mx(l/2),my(2*r)-12);c.fillText('OVAL '+t.length.toFixed(0)+' m',w/2,h/2);c.fillText('ASPHALT · RETAKAN · POLISI TIDUR',w/2,h-5);
  for(const p of s.potholes){const x=(p.longitude-s.config.origin.longitude)*Math.PI/180*6378137*Math.cos(s.config.origin.latitude*Math.PI/180),y=(p.latitude-s.config.origin.latitude)*Math.PI/180*6378137;c.fillStyle='#f5b75a';c.beginPath();c.arc(mx(x),my(y),3.5,0,Math.PI*2);c.fill();}
  c.save();c.translate(mx(s.pose.x),my(s.pose.y));c.rotate(-s.pose.yaw);c.fillStyle='#9be7c4';c.beginPath();c.moveTo(7,0);c.lineTo(-5,-4);c.lineTo(-3,0);c.lineTo(-5,4);c.closePath();c.fill();c.restore();
}
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
  $('progress').style.width=(100*s.track_progress)+'%';
  $('trackLabel').textContent='Arena oval · '+s.config.track.length.toFixed(0)+' m / putaran';
  $('fps').textContent=s.vision.fps.toFixed(1)+' FPS';$('latency').textContent=s.vision.latency_ms.toFixed(1)+' ms / frame';
  $('visionFlag').textContent=!s.options.vision?'VISION NONAKTIF':s.vision.detections.length?'DUGAAN LUBANG TERDETEKSI':'TIDAK ADA DETEKSI';$('visionFlag').classList.toggle('warn',s.vision.detections.length>0);
  renderImu(s);
  const warn=s.buzzer.active;
  $('alertPanel').classList.toggle('warning',warn);$('alertSymbol').textContent=warn?'!':'✓';
  $('alertTitle').textContent=warn?'Waspada jalan rusak':healthy?'Tidak ada peringatan':'Menunggu sensor';
  $('alertDetail').textContent=warn?s.buzzer.sources.join(' + ')+(s.db_warning?' · '+s.db_warning.distance.toFixed(1)+' m di depan':' · terdeteksi pada kamera'):s.imu.calibrating?'Kalibrasi IMU; sepeda ditahan selama 2 detik.':!soundOn?'Suara nonaktif · klik Aktifkan suara.':'Kamera dan cache lokasi sedang dipantau.';
  $('roadAlert').hidden=!warn;$('roadAlertSub').textContent=s.buzzer.sources.join(' + ')+(s.db_warning?' · estimasi '+s.db_warning.eta.toFixed(1)+' detik':' · kamera depan');
  if(warn)beep();
  $('cacheCount').textContent=s.storage.cached+' TITIK';$('reports').textContent=s.storage.total_reports;$('pending').textContent=s.storage.pending;
  $('syncStatus').textContent=!s.options.online?'● Offline · cache tetap aktif':s.sync.error?'● Server belum tersambung':'● Sinkron · '+s.sync.ms.toFixed(0)+' ms';
  for(const option of ['vision','imu','database','online']){const input=$('opt-'+option);if(document.activeElement!==input)input.checked=s.options[option];}
  $('auto').classList.toggle('active',s.options.autopilot);$('auto').textContent=s.options.autopilot?'Ⅱ Hentikan demo':'▷ Demo otomatis';
  $('health').textContent=Object.entries(s.health).map(([k,v])=>k.toUpperCase()+' '+(v?'●':'○')).join('  ');
  const key=s.events[0]?.wall+':'+s.events.length;
  if(key!==lastEventKey){lastEventKey=key;$('events').innerHTML=s.events.map(e=>`<div class="event ${esc(e.level)}"><time>${esc(e.time)}</time><div><strong>${esc(e.kind)}</strong><p>${esc(e.message)}</p></div></div>`).join('');}
  drawChart(s);drawMap(s);
}
async function poll(){try{const r=await fetch('/api/state');if(!r.ok)throw Error('server');state=await r.json();render(state);}catch(e){$('connection').textContent='DASHBOARD TERPUTUS';$('liveDot').classList.remove('ready');$('alertTitle').textContent='Koneksi terputus';$('alertDetail').textContent='Periksa terminal launcher. Sepeda direm otomatis.';}setTimeout(poll,150);}
setInterval(()=>$('clock').textContent=new Date().toLocaleTimeString('id-ID',{hour12:false}).replaceAll('.',':'),1000);
poll();
