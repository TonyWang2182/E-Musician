// Control only the explicitly enabled loopback debug port of our owned WebView.
// This calls the actual form/buttons; it never substitutes application state.
import {readFile} from 'node:fs/promises';
const [portText,action,...args]=process.argv.slice(2);
const port=Number(portText);
if(!Number.isInteger(port)||port<1024||port>65535)throw new Error('Explicit owned WebView port required');
const pages=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const target=pages.find(p=>p.type==='page'&&/^http:\/\/127\.0\.0\.1:\d+\//.test(p.url));
if(!target)throw new Error('Owned local assistant page is not ready');
const socket=new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
const pending=new Map();let sequence=0;
socket.onmessage=event=>{const m=JSON.parse(event.data),p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(new Error(JSON.stringify(m.error))):p.resolve(m.result)}};
function send(method,params={}){return new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))})}
try{
 await send('Runtime.enable');
 let expression;
 if(action==='status')expression=`(()=>{const visible=e=>!!e&&!e.hidden&&e.getClientRects().length>0;const text=id=>document.getElementById(id)?.textContent.trim()||'';return {connected:text('connection'),phase:text('phase'),progress:text('progress-copy'),notice:text('notice-text'),plan:visible(document.getElementById('plan')),planSummary:text('plan-summary'),preview:text('generation-preview-status'),result:text('result-text'),buttons:[...document.querySelectorAll('button[id]')].filter(visible).map(e=>({id:e.id,text:e.textContent.trim(),disabled:e.disabled})),language:document.documentElement.lang,presentation:document.body.classList.contains('presentation-workspace')}})()`;
 else if(action==='reload'){await send('Page.reload',{ignoreCache:true});expression='({reloaded:true})';}
 else if(action==='scene'){
  const manifest=JSON.parse(await readFile(args[0],'utf8'));
  const scene=manifest.scenarios.find(s=>s.id===args[1]);if(!scene)throw new Error('Unknown prepared scene');
  expression=`(()=>{const p=document.getElementById('prompt'),scope=document.getElementById('scope');scope.value=${JSON.stringify(scene.kind==='generate'?'project':'selection')};scope.dispatchEvent(new Event('change',{bubbles:true}));p.value=${JSON.stringify(scene.prompts[0])};p.dispatchEvent(new Event('input',{bubbles:true}));if(document.getElementById('submit').disabled)throw new Error('Send is disabled');document.getElementById('prompt-form').requestSubmit();return {submitted:true}})()`;
 }else if(action==='click'){
  if(!['apply','undo','generation-play','generation-stop','cancel-work','discard'].includes(args[0]))throw new Error('Button is not in the capture workflow');
  expression=`(async()=>{const deadline=Date.now()+12000;while(Date.now()<deadline){const e=document.getElementById(${JSON.stringify(args[0])});if(e&&!e.hidden&&e.getClientRects().length&&!e.disabled){e.scrollIntoView({block:'nearest'});e.click();return {clicked:e.id}}await new Promise(r=>setTimeout(r,150));}throw new Error('Requested visible button unavailable after bounded wait')})()`;
 }else throw new Error('Use status, scene <manifest> <id>, or click <button>');
 const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
 if(result.exceptionDetails)throw new Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);
 console.log(JSON.stringify(result.result.value));
}finally{socket.close()}
