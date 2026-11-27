const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const asset = path.join(root, 'scripts/music_agent/web');
const out = path.join(root, 'build-logs/agent-ui');
const testKey = 'synthetic-key-' + 'x'.repeat(1024);
fs.mkdirSync(out, {recursive: true});
const registry = [
  {id:'kimi',label:'Kimi',configured:true,adapter_ready:true,model:'kimi-k2.6',default_model:'kimi-k2.6',base_url:'https://api.moonshot.cn/v1',models:['kimi-k2.6']},
  {id:'openai',label:'OpenAI',configured:false,adapter_ready:true,model:'gpt-5-mini',default_model:'gpt-5-mini',base_url:'https://api.openai.com/v1',models:['gpt-5-mini']},
  {id:'anthropic',label:'Anthropic',configured:false,adapter_ready:false,model:'',base_url:'',models:[]}
];
const initial = {
  phase:'idle',busy:false,detail:'',
  snapshot:{project_id:'synthetic-project',revision:1,name:'Synthetic interface test · Morning study',bpm:120,numerator:4,denominator:4,selected_track_id:'t1',selected_clip_id:'c1',
    selection_context:{available:true,selection_revision:3,active_track_id:'t1',active_clip_id:'c1',track_ids:['t1'],clip_ids:['c1'],note_clip_id:'c1',note_ids:['n1','n2'],time_range:{active:true,start_seconds:0,end_seconds:8},focus:'piano_roll'},
    tracks:[{id:'t1',name:"Piano",colour:'#91A7C3',kind:'instrument',clips:[{id:'c1',name:'Lead melody'}]},{id:'t2',name:'<img src=x onerror=alert(1)>',colour:'url(https://invalid.test)',kind:'audio',clip_count:1}]},
  plan:null,messages:[],provider:structuredClone(registry[0]),providers:structuredClone(registry),
  usage:{calls:0,prompt_tokens:0,completion_tokens:0},can_undo:false,last_result:'',error:null,control:{connected:true},
  capability_groups:[{id:'track_colour',label:"Track colour",status_label:"Available",enabled:true,example:"Set the selected track colour to muted teal #BFD2CF. Show the change first.",detail:"Select a whole track or choose Whole project scope. Colour changes do not affect sound."}]
};
let state = structuredClone(initial), rejectShutdown = false, lastPlan = null, lastSettings = null;
const count = {get:0,plan:0,apply:0,undo:0,shutdown:0,settings:0,cancel:0,pause:0,resume:0};
const server = http.createServer(async (req,res) => {
  const pathname = new URL(req.url,'http://127.0.0.1').pathname;
  if (pathname.startsWith('/api/')) {
    assert.equal(req.headers['x-agent-token'],'fixture-session');
    const chunks=[]; for await (const c of req) chunks.push(c);
    const raw=Buffer.concat(chunks), body=raw.length ? JSON.parse(raw) : {};
    if (pathname === '/api/state') count.get++;
    if (pathname === '/api/plan') {
      count.plan++;lastPlan=body;assert.deepEqual(Object.keys(body).sort(),['prompt','scope']);assert.ok(['selection','project'].includes(body.scope));
      state.phase='ready';state.error=null;state.last_result='';state.progress={stage:'ready',label:'Review the complete plan before applying.',completed:0,total:0};
      state.plan={id:'p'+count.plan,scope:{mode:body.scope,project_revision:state.snapshot.revision,selection_revision:3},revision:state.snapshot.revision,summary:body.scope==='project'?'Change the fixed project tempo':'Transpose the two selected notes',changes:body.scope==='project'?['Project tempo: 120 → 100 BPM','MIDI retains beat positions; audio retains original speed.']:['Piano / Lead melody: edit only the two selected notes.','Pitch +12 semitones; preserve start, length and velocity.']};
      state.plan.steps=[{index:1,label:body.scope==='project'?'Change project tempo':'Transpose the two selected notes'}];
      state.messages.push({role:'user',content:body.prompt},{role:'assistant',content:'The edit plan is ready. Review before applying.'});
      state.usage={calls:count.plan,prompt_tokens:913*count.plan,completion_tokens:85*count.plan};
    }
    if (pathname === '/api/apply') {count.apply++;assert.equal(body.plan_id,state.plan.id);state.phase='done';state.snapshot.bpm=100;state.snapshot.revision++;state.last_result='Applied one edit and verified project tempo at 100 BPM.';state.can_undo=true;state.progress={stage:'done',label:'All changes verified.',completed:1,total:1};}
    if (pathname === '/api/undo') {count.undo++;state.snapshot.bpm=120;state.can_undo=false;state.last_result='This edit was undone.';}
    if (pathname === '/api/settings') {
      count.settings++;lastSettings=body;const entry=state.providers.find(p=>p.id===body.provider);assert.ok(entry.adapter_ready);
      entry.model=body.model;entry.base_url=body.base_url||entry.base_url;entry.configured=entry.configured||!!body.api_key;state.provider=structuredClone(entry);
    }
    if (pathname === '/api/cancel') {count.cancel++;state.phase='cancelled';state.busy=false;state.plan=null;if('pause_requested' in state)state.pause_requested=false;state.progress={stage:'cancelled',label:'Stopped without submitting further changes.',completed:0,total:0};}
    if (pathname === '/api/pause') {count.pause++;assert.deepEqual(body,{});assert.equal(state.phase,'planning');state.pause_requested=true;state.progress={stage:'planning',label:'Pause after the current step.',completed:0,total:0};}
    if (pathname === '/api/resume') {count.resume++;assert.deepEqual(body,{});assert.equal(state.phase,'paused');state.phase='planning';state.pause_requested=false;state.progress={stage:'planning',label:'Continue preparing the plan.',completed:0,total:0};}
    if (pathname === '/api/shutdown') {
      if (rejectShutdown) {res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({error:'The project is unsaved. Return to the DAW to save.'}));return;}
      count.shutdown++;assert.equal(body.confirm,true);
    }
    res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(state));return;
  }
  const file={'/':'index.html','/app.js':'app.js','/i18n.js':'i18n.js','/style.css':'style.css'}[pathname];
  if (!file) {res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Type':file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8'});res.end(fs.readFileSync(path.join(asset,file)));
});
async function waitReady(page) {
  await page.waitForFunction(()=>document.getElementById('connection').textContent==="DAW connected");
}
async function refresh(page) {
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
}
async function capture(page,name,width,height) {
  await page.setViewportSize({width,height});
  await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),name+' horizontal overflow');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollHeight<=innerHeight+1),name+' outer vertical overflow');
  assert.ok(await page.locator('#prompt').evaluate(e=>e.getBoundingClientRect().bottom<=innerHeight),name+' composer below viewport');
}
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({...(process.env.BROWSER_EXE?{executablePath:process.env.BROWSER_EXE}:{channel:'msedge'}),headless:true});
  const context=await browser.newContext();
  await context.addInitScript(()=>{
    window.nativeEvents=[];window.nativeListeners={};window.leakedKeys=[];
    window.__JUCE__={backend:{emitEvent:(name,data)=>window.nativeEvents.push({name,data}),addEventListener:(name,fn)=>{window.nativeListeners[name]=fn;}}};
    window.addEventListener('keydown',e=>window.leakedKeys.push(e.key));
  });
  const page=await context.newPage();
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>assert.ok(r.url().startsWith('http://127.0.0.1:')));
  const origin='http://127.0.0.1:'+server.address().port;
  try {
    await page.setViewportSize({width:340,height:740});
    await page.goto(origin+'/?embedded=1&lang=zh-CN#token=fixture-session');await waitReady(page);
    assert.equal(new URL(page.url()).hash,'');assert.equal(await page.locator('#scope').inputValue(),'selection');
    assert.equal(await page.locator('#standalone-footer').isVisible(),false);
    assert.equal(await page.locator('#collapse').isVisible(),true);
    assert.match(await page.locator('#context-pills').innerText(),/2 notes/);assert.match(await page.locator('#context-pills').innerText(),/0–8 s/);
    assert.equal(await page.locator('#capabilities').evaluate(e=>e.open),false);
    assert.equal(await page.locator('#context-pills').evaluate(e=>e.getBoundingClientRect().height<=48),true);
    assert.match(await page.locator('#tempo').evaluate(e=>getComputedStyle(e).fontFamily),/Consolas/);
    assert.match(await page.locator('#prompt').evaluate(e=>getComputedStyle(e).fontFamily),/Segoe UI/);
    assert.equal(await page.locator('.composer-dock').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(241, 242, 238)');
    await capture(page,'sidebar-idle-340',340,740);
    await page.locator('#capabilities > summary').click();await page.locator('.capability-row > summary').click();await page.locator('.capability-row button').click();
    assert.match(await page.locator('#prompt').inputValue(),/#BFD2CF/);assert.equal(count.plan,0);await refresh(page);assert.equal(await page.locator('#capabilities').evaluate(e=>e.open),true);await page.locator('#capabilities > summary').click();
    await page.locator('#project-details summary').click();
    assert.equal(await page.locator('.track-name').nth(1).textContent(),'<img src=x onerror=alert(1)>');assert.equal(await page.locator('.tracks img').count(),0);
    assert.equal(await page.locator('.track-name').first().evaluate(e=>getComputedStyle(e,'::before').backgroundColor),'rgb(145, 167, 195)');assert.equal(await page.locator('#tracks li').nth(1).evaluate(e=>e.style.getPropertyValue('--track-colour')),'');
    await page.locator('#project-details summary').click();
    await page.reload();await waitReady(page);assert.equal(new URL(page.url()).search,'?embedded=1&lang=zh-CN');
    await page.locator('#prompt').fill('Raise the two selected notes by one octave');await page.locator('#submit').click();await page.locator('#apply').waitFor({state:'visible'});
    assert.equal(lastPlan.scope,'selection');assert.equal(count.apply,0);
    assert.equal(await page.locator('#plan-sequence').isVisible(),true);assert.deepEqual(await page.locator('#plan-steps li').allTextContents(),['Transpose the two selected notes']);
    for (const [name,width,height] of [['sidebar-ready-340',340,740],['sidebar-ready-560',560,820],['sidebar-edge-260',260,540]]) await capture(page,name,width,height);
    await page.locator('#scope').selectOption('project');assert.match(await page.locator('#plan-scope').innerText(),/selection when sent/);
    await page.locator('#discard').click();await page.waitForFunction(()=>document.getElementById('phase').textContent==="Stopped");
    await page.setViewportSize({width:340,height:740});
    await page.locator('#prompt').fill('Set project tempo to 100 BPM');await page.locator('#submit').click();await page.locator('#apply').waitFor({state:'visible'});assert.equal(lastPlan.scope,'project');assert.equal(state.snapshot.bpm,120);
    assert.match(await page.locator('#plan-scope').innerText(),/whole project/);state.snapshot.revision=2;await refresh(page);assert.match(await page.locator('#plan-revision').innerText(),/Revision 1/);state.snapshot.revision=1;
    await page.locator('#apply').click();await page.waitForFunction(()=>document.getElementById('tempo').textContent==='100 BPM');assert.equal(count.apply,1);
    await page.locator('#undo').click();await page.waitForFunction(()=>document.getElementById('tempo').textContent==='120 BPM');assert.equal(count.undo,1);
    const afterEdit=structuredClone(state), writesBefore=count.apply, cancelsBefore=count.cancel;
    state.phase='ready';state.progress=null;state.plan={id:'colour-synthetic',scope:{mode:'project'},revision:state.snapshot.revision,summary:'Change the piano track colour.',changes:['Track Piano colour: #91A7C3 → #BFD2CF (sound unchanged)']};state.last_result='';await refresh(page);
    assert.deepEqual(await page.locator('#changes .colour-value').allTextContents(),['#91A7C3','#BFD2CF']);assert.equal(await page.locator('#changes .colour-value').last().evaluate(e=>getComputedStyle(e,'::before').backgroundColor),'rgb(191, 210, 207)');assert.equal(await page.locator('#apply').isDisabled(),false);assert.equal(count.apply,writesBefore);
    await capture(page,'sidebar-colour-review-340',340,740);await page.evaluate(()=>window.emusicianSetLanguage('en'));await capture(page,'sidebar-colour-review-en-340',340,740);assert.equal(await page.locator('#apply').innerText(),'Apply changes');await page.evaluate(()=>window.emusicianSetLanguage('zh-CN'));
    state.phase='ready';state.plan={id:'notes-synthetic',scope:{mode:'project'},revision:state.snapshot.revision,summary:'Add explicit notes to two clips.',changes:['Test piano / New clip: add 2 notes.','Melody track / Second clip: add 1 note.'],note_previews:[{label:'Test piano / New clip',notes:[{pitch:60,start_beats:0,length_beats:1,velocity:80,channel:1},{pitch:64,start_beats:1.125,length_beats:0.25,velocity:90,channel:2}]},{label:'<img src=x onerror=alert(1)>',notes:[{pitch:67,start_beats:2,length_beats:0.5,velocity:70,channel:16}]}]};state.last_result='';state.progress=null;
    await refresh(page);assert.equal(await page.locator('#note-preview-summary').innerText(),'New notes (3)');assert.equal(await page.locator('#note-previews').evaluate(e=>e.open),false);assert.equal(await page.locator('.note-preview-row').count(),0);
    await page.locator('#note-preview-summary').click();await page.waitForFunction(()=>document.querySelectorAll('.note-preview-row').length===3);
    assert.match(await page.locator('.note-preview-help').innerText(),/New notes before later plan steps/);assert.match(await page.locator('.note-preview-help').innerText(),/quarter-note beats within the clip/);
    assert.match(await page.locator('.note-preview-row').nth(0).innerText(),/MIDI pitch 60/);assert.deepEqual(await page.locator('.note-preview-row').nth(0).locator('dd').allTextContents(),['0 beats','1 beats','80','1']);assert.deepEqual(await page.locator('.note-preview-row').nth(1).locator('dd').allTextContents(),['1.125 beats','0.25 beats','90','2']);assert.deepEqual(await page.locator('.note-preview-row').nth(2).locator('dd').allTextContents(),['2 beats','0.5 beats','70','16']);assert.equal(await page.locator('#note-preview-rows img').count(),0);assert.equal(await page.locator('.note-preview-group h4').nth(1).textContent(),'<img src=x onerror=alert(1)>');assert.equal(await page.locator('#note-preview-pager').isVisible(),false);
    await page.evaluate(()=>{window.savedPreviewRow=document.querySelector('.note-preview-row');});await refresh(page);assert.equal(await page.locator('#note-previews').evaluate(e=>e.open),true);assert.equal(await page.evaluate(()=>window.savedPreviewRow===document.querySelector('.note-preview-row')),true);
    await capture(page,'sidebar-note-preview-340',340,740);await capture(page,'sidebar-note-preview-260',260,540);await page.setViewportSize({width:340,height:740});
    await page.locator('#note-preview-summary').click();await page.locator('#note-preview-summary').click();assert.equal(await page.evaluate(()=>window.savedPreviewRow===document.querySelector('.note-preview-row')),true);
    state.plan={...state.plan,id:'notes-2000-synthetic',changes:['Test piano / Long clip: add 2000 notes.'],note_previews:[{label:'Test piano / Long clip',notes:Array.from({length:2000},(_,i)=>({pitch:60+i%12,start_beats:i/8,length_beats:0.125,velocity:80,channel:1}))}]};await refresh(page);assert.equal(await page.locator('#note-previews').evaluate(e=>e.open),false);assert.equal(await page.locator('.note-preview-row').count(),0);assert.equal(await page.locator('#note-preview-summary').innerText(),'New notes (2000)');
    await page.locator('#note-preview-summary').click();await page.waitForFunction(()=>document.querySelectorAll('.note-preview-row').length===50);assert.equal(await page.locator('#note-preview-page').innerText(),'1–50 of 2000');assert.equal(await page.locator('#note-preview-prev').isDisabled(),true);
    await page.locator('#note-preview-next').click();assert.equal(await page.locator('#note-preview-page').innerText(),'51–100 of 2000');await page.evaluate(()=>{window.savedPreviewRow=document.querySelector('.note-preview-row');});await refresh(page);assert.equal(await page.locator('#note-preview-page').innerText(),'51–100 of 2000');assert.equal(await page.evaluate(()=>window.savedPreviewRow===document.querySelector('.note-preview-row')),true);
    await page.evaluate(()=>{for(let i=0;i<38;i++)document.getElementById('note-preview-next').click();});assert.equal(await page.locator('#note-preview-page').innerText(),'1951–2000 of 2000');assert.equal(await page.locator('#note-preview-next').isDisabled(),true);assert.equal(await page.locator('.note-preview-row').count(),50);assert.deepEqual(await page.locator('.note-preview-row').last().locator('dd').allTextContents(),['249.875 beats','0.125 beats','80','1']);assert.match(await page.locator('.note-preview-row').last().innerText(),/Note 2000/);
    await page.locator('#note-preview-prev').click();assert.equal(await page.locator('#note-preview-page').innerText(),'1901–1950 of 2000');assert.equal(count.apply,writesBefore);
    state.phase='ready';state.plan={id:'destructive-synthetic',scope:{mode:'selection'},revision:state.snapshot.revision,summary:'Organize notes and clips in the current selection.',steps:[{index:1,label:'Delete selected notes in Lead melody'},{index:2,label:'Delete the transition clip'}],changes:['Piano / Lead melody: delete 2 selected notes; preserve all others.','Drums / Transition: delete 1 clip; preserve source files.']};state.last_result='';state.progress=null;
    await refresh(page);assert.equal(await page.locator('#note-previews').isVisible(),false);assert.equal(await page.locator('.note-preview-row').count(),0);assert.deepEqual(await page.locator('#plan-steps li').allTextContents(),['Delete selected notes in Lead melody','Delete the transition clip']);assert.equal(await page.locator('#changes .change-action').count(),2);assert.match(await page.locator('#changes').innerText(),/delete 2 selected notes/);assert.match(await page.locator('#changes').innerText(),/delete 1 clip/);assert.equal(count.apply,writesBefore);
    await capture(page,'sidebar-sequence-340',340,740);await capture(page,'sidebar-sequence-260',260,540);await page.setViewportSize({width:340,height:740});
    const readableChanges=structuredClone(state.plan.changes);state.plan.changes=[{internal_id:'never-show-code'}];await refresh(page);assert.equal(await page.locator('#apply').isDisabled(),true);assert.match(await page.locator('#notice').innerText(),/plan description is incomplete/);assert.doesNotMatch(await page.locator('#changes').innerText(),/internal_id|never-show-code/);state.plan.changes=readableChanges;
    delete state.plan.steps;await refresh(page);assert.equal(await page.locator('#plan-sequence').isVisible(),false);assert.equal(await page.locator('#apply').isDisabled(),false);
    state.phase='applying';state.busy=true;state.plan=null;state.can_undo=false;
    for(const [stage,label] of [['preflight','Checking the project and selection.'],['submitting','The complete batch was submitted. Waiting for the result.'],['verifying','Verifying edit results.']]){
      state.progress={stage,label,completed:stage==='verifying'?1:0,total:2};await refresh(page);
      assert.equal(await page.locator('#execution-stages [aria-current="step"]').getAttribute('data-stage'),stage);assert.equal(await page.locator('#busy-detail').innerText(),label);assert.equal(await page.locator('#cancel-work').isVisible(),false);assert.equal(await page.locator('#pause-work').isVisible(),false);assert.equal(await page.locator('#commit-hint').isVisible(),true);assert.doesNotMatch(await page.locator('#execution-stages').innerText(),/50%|1\s*\/\s*2/);
      await page.locator('#cancel-work').evaluate(e=>e.dispatchEvent(new MouseEvent('click')));await page.locator('#pause-work').evaluate(e=>e.dispatchEvent(new MouseEvent('click')));assert.equal(count.cancel,cancelsBefore);assert.equal(count.pause,0);
      if(stage==='submitting')await capture(page,'sidebar-submitting-340',340,740);
    }
    state.phase='done';state.busy=false;state.progress={stage:'done',label:'The complete batch was verified.',completed:2,total:2};state.last_result='The batch is complete and can be undone in one step.';state.can_undo=true;await refresh(page);assert.equal(await page.locator('#execution-stages li[data-status="complete"]').count(),4);assert.equal(await page.locator('#undo').isDisabled(),false);
    state.progress={stage:'done',label:'Answered the project question.',completed:0,total:0};await refresh(page);assert.equal(await page.locator('#execution-stages').isVisible(),false);
    state.phase='planning';state.busy=true;state.plan=null;state.last_result='';state.pause_requested=false;state.progress={stage:'planning',label:'Preparing an edit plan.',completed:0,total:0};await refresh(page);assert.equal(await page.locator('#pause-work').innerText(),"Pause");assert.equal(await page.locator('#pause-work').isDisabled(),false);
    await page.locator('#pause-work').click();await page.waitForFunction(()=>document.getElementById('pause-work').textContent==="Pausing");assert.equal(count.pause,1);assert.equal(await page.locator('#pause-work').isDisabled(),true);
    state.phase='paused';state.progress={stage:'paused',label:'Paused. Resume to continue with the next step.',completed:0,total:0};await refresh(page);assert.equal(await page.locator('#phase').innerText(),"Paused");assert.equal(await page.locator('#pause-work').innerText(),"Resume");assert.equal(await page.locator('#cancel-work').isDisabled(),false);await capture(page,'sidebar-paused-340',340,740);await capture(page,'sidebar-paused-260',260,540);await page.setViewportSize({width:340,height:740});
    await page.locator('#pause-work').click();await page.waitForFunction(()=>document.getElementById('pause-work').textContent==="Pause");assert.equal(count.resume,1);
    state.phase='paused';await refresh(page);await page.locator('#cancel-work').click();await page.waitForFunction(()=>document.getElementById('phase').textContent==="Stopped");assert.equal(count.cancel,cancelsBefore+1);assert.equal(count.apply,writesBefore);
    state.phase='planning';state.busy=true;delete state.pause_requested;state.progress=null;await refresh(page);assert.equal(await page.locator('#pause-work').isVisible(),false);
    state=afterEdit;await refresh(page);
    await page.locator('#settings-toggle').click();
    assert.equal(await page.locator('.work-area').evaluate(e=>e.inert),true);
    assert.equal(await page.locator('#provider option[value="anthropic"]').evaluate(option=>option.disabled),true);
    await page.locator('#connection-settings summary').click();await refresh(page);assert.equal(await page.locator('#connection-settings').getAttribute('open'),'');
    await page.locator('#api-key').fill('not-a-real-key');
    await page.locator('#provider').selectOption('openai');assert.equal(await page.locator('#api-key').inputValue(),'');assert.equal(await page.locator('#model').inputValue(),'gpt-5-mini');assert.match(await page.locator('#provider-status').innerText(),/No key/);
    await page.locator('#settings').evaluate(e=>{e.scrollTop=0;});await capture(page,'sidebar-settings-340',340,740);
    await page.locator('#api-key').fill(testKey);await page.locator('#settings-save').click();await page.waitForFunction(()=>document.getElementById('settings-feedback').textContent.includes('Settings saved'));
    assert.equal(lastSettings.provider,'openai');assert.equal(lastSettings.base_url,'https://api.openai.com/v1');assert.equal(lastSettings.api_key,testKey);
    assert.equal(await page.locator('#api-key').inputValue(),'');assert.equal(await page.evaluate(()=>JSON.stringify(localStorage)),'{}');assert.equal(await page.evaluate(()=>JSON.stringify(sessionStorage).includes('synthetic-key-')),false);
    await page.keyboard.press('Escape');assert.equal(await page.locator('#settings').isVisible(),false);assert.equal(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentClose').length),0);assert.equal(await page.locator('.work-area').evaluate(e=>e.inert),false);
    await page.locator('#prompt').focus();assert.deepEqual(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentFocus').at(-1)),{name:'agentFocus',data:{focused:true}});
    await page.locator('#prompt').evaluate(e=>e.blur());assert.deepEqual(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentFocus').at(-1).data),{focused:false});
    await page.locator('#prompt').focus();await page.evaluate(()=>window.dispatchEvent(new Event('blur')));assert.equal(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentFocus').at(-1).data.focused),false);
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));assert.equal(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentFocus').at(-1).data.focused),true);
    await page.locator('#prompt').fill('Keep this draft');await page.keyboard.press('Space');await page.keyboard.press('Control+4');
    const draft=await page.locator('#prompt').inputValue();assert.equal(draft,'Keep this draft ');
    await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentClose').length),1);assert.equal(await page.locator('#prompt').inputValue(),draft);assert.equal(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentFocus').at(-1).data.focused),false);
    await page.locator('#prompt').evaluate(e=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true})));
    assert.equal(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentClose').length),1);assert.deepEqual(await page.evaluate(()=>window.leakedKeys),[]);
    await page.locator('#collapse').click();assert.equal(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentClose').length),2);assert.equal(count.shutdown,0);
    await page.locator('#prompt').focus();await page.keyboard.press('Control+Shift+A');assert.equal(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentClose').length),3);assert.equal(await page.locator('#prompt').inputValue(),draft);assert.equal(count.shutdown,0);
    await page.locator('#prompt').focus();await page.evaluate(()=>window.nativeListeners.agentVisibility({visible:false}));const getBefore=count.get;
    assert.equal(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentFocus').at(-1).data.focused),false);assert.equal(await page.locator('#prompt').evaluate(e=>document.activeElement===e),false);
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));assert.equal(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentFocus').at(-1).data.focused),false);
    await new Promise(resolve=>setTimeout(resolve,2800));assert.equal(count.get,getBefore);
    await page.evaluate(()=>window.nativeListeners.agentVisibility({visible:true}));await page.waitForFunction(()=>!document.getElementById('refresh').disabled);assert.ok(count.get>getBefore);assert.equal(await page.locator('#prompt').inputValue(),draft);
    assert.equal(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentFocus').at(-1).data.focused),false);await page.locator('#prompt').click();assert.equal(await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentFocus').at(-1).data.focused),true);
    for(const event of await page.evaluate(()=>window.nativeEvents.filter(e=>e.name==='agentFocus'))){assert.deepEqual(Object.keys(event.data),['focused']);assert.equal(typeof event.data.focused,'boolean');}
    state.phase='cancelled';state.busy=true;await refresh(page);assert.equal(await page.locator('#prompt').isDisabled(),true);state.busy=false;
    state.snapshot.selection_context={available:false,notes_truncated:true,note_count:3000,note_ids:[]};await refresh(page);await page.locator('#scope').selectOption('selection');assert.match(await page.locator('#context-pills').innerText(),/3000 notes · over the limit/);assert.match(await page.locator('#scope-hint').innerText(),/Select up to 2,000 notes/);
    state.snapshot.selection_context={available:true,focus:'track',active_track_id:'t1',track_ids:[],clip_ids:[],note_ids:[]};await refresh(page);assert.match(await page.locator('#context-pills').innerText(),/Track: Piano/);assert.doesNotMatch(await page.locator('#context-pills').innerText(),/No objects selected/);
    state.snapshot.selection_context={available:false};await refresh(page);assert.match(await page.locator('#context-pills').innerText(),/Full selection unavailable/);assert.doesNotMatch(await page.locator('#context-pills').innerText(),/2 notes/);
    state.error='The selection changed. Prepare a new plan.';state.phase='error';await refresh(page);await capture(page,'sidebar-error-340',340,740);assert.ok(await page.locator('#notice').evaluate(e=>{const r=e.getBoundingClientRect();const p=document.getElementById('transcript').getBoundingClientRect();return r.top>=p.top&&r.bottom<=p.bottom;}));
    await page.close();
    state=structuredClone(initial);
    const standalone=await context.newPage();standalone.on('pageerror',e=>errors.push(e.message));
    await standalone.setViewportSize({width:1280,height:800});await standalone.goto(origin+'/?lang=zh-CN#token=fixture-session');await waitReady(standalone);
    assert.equal(await standalone.locator('#collapse').isVisible(),false);assert.equal(await standalone.locator('#standalone-footer').isVisible(),true);
    await standalone.locator('#scope').selectOption('project');await standalone.locator('#prompt').fill('Set project tempo to 100 BPM');await standalone.locator('#submit').click();await standalone.locator('#apply').waitFor({state:'visible'});
    await capture(standalone,'standalone-1280',1280,800);
    await standalone.locator('#shutdown').click();await standalone.locator('#shutdown-cancel').click();assert.equal(count.shutdown,0);
    rejectShutdown=true;await standalone.locator('#shutdown').click();await standalone.locator('#shutdown-confirm').click();await standalone.waitForFunction(()=>document.getElementById('shutdown-feedback').textContent.includes('The project is unsaved'));assert.equal(count.shutdown,0);
    rejectShutdown=false;await standalone.locator('#shutdown-confirm').click();await standalone.waitForFunction(()=>document.getElementById('connection').textContent==="Assistant closed");assert.equal(count.shutdown,1);assert.equal(await standalone.evaluate(()=>sessionStorage.length),0);
    assert.equal(await standalone.evaluate(()=>window.nativeEvents.length),0);
    assert.deepEqual(errors,[]);
    console.log('PASS: synthetic sidebar at 260/340/560 and standalone1280; scoped plan/apply/Undo, exact added-note fields with lazy50 paging through2000 and refresh preservation, provider registry and per-provider key handling, unavailable selection, cancellation cleanup, native collapse/IME/keyboard/draft preservation, boolean-only focus hints and blur/hide clearing, hidden polling pause/resume, exact shutdown boundary, escaped data, no overflow. No real model, WebView2 host or DAW was tested.');
  } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
