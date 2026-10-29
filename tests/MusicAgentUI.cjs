const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const asset = path.join(root, 'scripts/music_agent/web');
const out = path.join(root, 'build-logs/agent-ui');
fs.mkdirSync(out,{recursive:true});
const initial = {phase:'idle',busy:false,snapshot:{project_id:'synthetic-project',revision:1,name:'合成浏览器测试 · Morning study',bpm:120,numerator:4,denominator:4,selected_track_id:'t1',selected_clip_id:'c1',tracks:[{id:'t1',name:'钢琴',kind:'instrument',clips:[{id:'c1',name:'主旋律'}]},{id:'t2',name:'<img src=x onerror=alert(1)>',kind:'audio',clip_count:1}]},plan:null,messages:[],provider:{configured:true,model:'kimi-k2.6',base_url:'https://api.moonshot.cn/v1'},usage:{calls:0,prompt_tokens:0,completion_tokens:0},can_undo:false,last_result:'',control:{connected:true}};
let rejectShutdown=false;
let state = structuredClone(initial), count = {plan:0,apply:0,undo:0,shutdown:0,settings:0,cancel:0}, receivedKey=false;
const server = http.createServer(async(req,res)=>{
  if(req.url.startsWith('/api/')) {
    assert.equal(req.headers['x-agent-token'],'fixture-session');
    const chunks=[]; for await(const c of req) chunks.push(c);
    const body=Buffer.concat(chunks).length ? JSON.parse(Buffer.concat(chunks)) : {};
    if(req.url==='/api/plan') { count.plan++; state.phase='ready'; state.plan={id:'p1',expected_revision:1,summary:'调整固定速度',changes:['工程速度：120 → 100 BPM','MIDI 保持拍位；音频保持原速。']}; state.messages=[{role:'user',content:body.prompt},{role:'assistant',content:'已准备修改方案，请核对后应用。'}];state.usage={calls:1,prompt_tokens:913,completion_tokens:85}; }
    if(req.url==='/api/apply') { count.apply++; assert.equal(body.plan_id,'p1');state.phase='done';state.snapshot.bpm=100;state.snapshot.revision=2;state.last_result='已应用 1 项修改，并回读确认工程速度为 100 BPM。';state.can_undo=true; }
    if(req.url==='/api/undo') { count.undo++; state.snapshot.bpm=120;state.can_undo=false;state.last_result='本次修改已撤销。'; }
    if(req.url==='/api/settings') { count.settings++; receivedKey=body.api_key==='test-placeholder-key';state.provider.model=body.model; }
    if(req.url==='/api/cancel') { count.cancel++;state.phase='cancelled';state.plan=null; }
    if(req.url==='/api/shutdown') {if(rejectShutdown){res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({error:'工程未保存，请返回 DAW 保存。'}));return;} count.shutdown++;assert.equal(body.confirm,true);}
    res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(state));return;
  }
  const file = {'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[req.url];
  if(!file){res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Type':file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8'});res.end(fs.readFileSync(path.join(asset,file)));
});
(async()=>{
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await chromium.launch({...(process.env.BROWSER_EXE ? {executablePath:process.env.BROWSER_EXE} : {channel:'msedge'}),headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:800}});
  let errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>assert.ok(r.url().startsWith('http://127.0.0.1:')));
  const origin=`http://127.0.0.1:${server.address().port}`;
  try {
    await page.goto(origin+'/#token=fixture-session');await page.waitForFunction(()=>document.getElementById('connection').textContent==='DAW 已连接');
    assert.equal(new URL(page.url()).hash,'');assert.equal(await page.locator('.track-name').nth(1).textContent(),'<img src=x onerror=alert(1)>');assert.equal(await page.locator('.tracks img').count(),0);
    await page.reload();await page.waitForFunction(()=>document.getElementById('connection').textContent==='DAW 已连接');
    await page.locator('#prompt').fill('把工程速度改为 100 BPM');await page.locator('#submit').click();await page.locator('#apply').waitFor({state:'visible'});assert.equal(count.apply,0);assert.equal(state.snapshot.bpm,120);
    await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
    await page.setViewportSize({width:1000,height:650});await page.screenshot({path:path.join(out,'compact.png'),fullPage:true});
    for(const width of [1280,1000,390]) {await page.setViewportSize({width,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
    await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
    await page.setViewportSize({width:1280,height:800});await page.locator('#apply').click();await page.waitForFunction(()=>document.getElementById('tempo').textContent==='100 BPM');assert.equal(count.apply,1);
    await page.locator('#undo').click();await page.waitForFunction(()=>document.getElementById('tempo').textContent==='120 BPM');assert.equal(count.undo,1);
    await page.locator('#settings-toggle').click();await page.locator('#api-key').fill('test-placeholder-key');await page.locator('#settings-save').click();await page.waitForFunction(()=>document.getElementById('settings-feedback').textContent.includes('设置已保存'));assert.equal(receivedKey,true);assert.equal(await page.locator('#api-key').inputValue(),'');assert.equal(await page.evaluate(()=>JSON.stringify(localStorage)), '{}');assert.equal(await page.evaluate(()=>JSON.stringify(sessionStorage).includes('test-placeholder-key')),false);
    await page.locator('#settings-toggle').click();await page.locator('#prompt').fill('再试一下');await page.locator('#submit').click();await page.locator('#discard').click();await page.waitForFunction(()=>document.getElementById('phase').textContent==='已停止');assert.equal(count.cancel,1);assert.equal(count.apply,1);
    state.phase='cancelled';state.busy=true;await page.locator('#refresh').click();await page.waitForFunction(()=>document.getElementById('prompt').disabled);state.busy=false;
    await page.locator('#refresh').click();await page.waitForFunction(()=>!document.getElementById('prompt').disabled);
    await page.locator('#shutdown').click();await page.locator('#shutdown-cancel').click();assert.equal(count.shutdown,0);
    rejectShutdown=true;await page.locator('#shutdown').click();await page.locator('#shutdown-confirm').click();await page.waitForFunction(()=>document.getElementById('shutdown-feedback').textContent.includes('工程未保存'));assert.equal(count.shutdown,0);rejectShutdown=false;await page.locator('#shutdown-confirm').click();await page.waitForFunction(()=>document.getElementById('connection').textContent==='助手已关闭');assert.equal(count.shutdown,1);assert.equal(await page.evaluate(()=>sessionStorage.length),0);
    assert.deepEqual(errors,[]);console.log('PASS: synthetic UI authentication/refresh, safe text, plan-before-apply, exact plan ID, Undo, settings secret handling, cancel, cleanup busy gate, shutdown confirmation, viewport overflow and screenshots. No real model or DAW used.');
  } finally {await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
