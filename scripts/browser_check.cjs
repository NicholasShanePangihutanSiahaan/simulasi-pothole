// Optional exhibit UI test; install Playwright separately (not a runtime dependency).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || '/tmp/pothole-browser/node_modules/playwright');
const fs=require('fs');
const path=require('path');
(async()=>{
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:1080},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const checks={javascript:false,responsive:false,keyboard:false,steering:false,gamepad_api:false,autopilot:false,audio_context:false};
  const url=process.env.DEMO_URL||'http://127.0.0.1:8765';
  const out=path.resolve('docs/images');fs.mkdirSync(out,{recursive:true});
  await page.goto(url,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('connection').textContent==='SIMULASI AKTIF',null,{timeout:40000});
  await page.waitForFunction(()=>document.getElementById('mainCamera').naturalWidth>0);
  await page.evaluate(async()=>{
    await fetch('/api/options',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({online:true,vision:true})});
    await fetch('/api/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario:'start'})});
  });
  await page.waitForTimeout(3000);
  await page.locator('#sound').click();
  checks.audio_context=await page.evaluate(()=>sound.state==='running');
  await page.locator('h1').click();
  await page.screenshot({path:path.join(out,'dashboard.png'),fullPage:true});
  if(process.env.BROWSER_DRIVE==='1'){
    // Browser-driven keyboard and standard Gamepad API mapping.
    await page.evaluate(()=>fetch('/api/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario:'start'})}));
    await page.waitForTimeout(3000);
    await page.keyboard.down('w');await page.waitForTimeout(1800);await page.keyboard.up('w');
    let speed=await page.evaluate(async()=>(await (await fetch('/api/state')).json()).pose.speed);
    if(speed<.2)throw Error('Keyboard tidak menggerakkan sepeda');
    checks.keyboard=true;
    await page.keyboard.down('w');await page.keyboard.down('a');await page.waitForTimeout(700);await page.keyboard.up('a');await page.keyboard.up('w');
    const yaw=await page.evaluate(async()=>(await (await fetch('/api/state')).json()).pose.yaw);
    if(yaw<.1)throw Error('Keyboard A tidak membelokkan sepeda ke kiri');
    checks.steering=true;
    await page.keyboard.down(' ');await page.waitForTimeout(1800);await page.keyboard.up(' ');
    await page.evaluate(()=>{
      window.testPad={connected:true,id:'DualSense synthetic test',axes:[0,0,0,0],buttons:Array.from({length:18},()=>({pressed:false,value:0}))};
      window.testPad.buttons[7]={pressed:true,value:.8};
      Object.defineProperty(navigator,'getGamepads',{value:()=>[window.testPad]});
    });
    await page.waitForTimeout(1800);
    speed=await page.evaluate(async()=>(await (await fetch('/api/state')).json()).pose.speed);
    if(speed<.2)throw Error('Gamepad API tidak menggerakkan sepeda');
    checks.gamepad_api=true;
    await page.evaluate(()=>{window.testPad.buttons[7]={pressed:false,value:0};window.testPad.buttons[6]={pressed:true,value:1};});
    await page.waitForTimeout(1500);
    await page.evaluate(()=>{window.testPad.connected=false;window.dispatchEvent(new Event('gamepaddisconnected'));});
    await page.waitForTimeout(1000);
    await page.evaluate(()=>fetch('/api/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario:'start'})}));
    await page.waitForTimeout(2600);
    await page.locator('#auto').click();
    await page.waitForTimeout(1800);
    let s=await page.evaluate(async()=>(await (await fetch('/api/state')).json()));
    if(!s.options.autopilot||s.pose.speed<.2)throw Error('Demo otomatis atau heartbeat tidak bekerja');
    await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
    await page.waitForTimeout(1000);
    s=await page.evaluate(async()=>(await (await fetch('/api/state')).json()));
    if(s.options.autopilot)throw Error('Demo otomatis tidak berhenti saat blur');
    checks.autopilot=true;
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.evaluate(()=>fetch('/api/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario:'start'})}));
    await page.waitForTimeout(2600);
    await page.screenshot({path:path.join(out,'dashboard.png'),fullPage:true});
  }
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(300);
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  await page.screenshot({path:path.join(out,'dashboard-mobile.png'),fullPage:true});
  if(overflow)throw Error('Horizontal overflow on mobile');
  checks.responsive=true;
  if(errors.length)throw Error(errors.join('\n'));
  checks.javascript=true;
  if(process.env.BROWSER_DRIVE==='1')fs.writeFileSync(path.resolve('docs/browser-validation.json'),JSON.stringify(checks,null,2));
  console.log('Browser OK: no JS errors, responsive layout'+(process.env.BROWSER_DRIVE==='1'?', keyboard and synthetic gamepad input':''));
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
