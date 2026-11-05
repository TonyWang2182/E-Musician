// Synthetic component capture in an owned headless Edge process only.
import {spawn} from "node:child_process";
import {readFile, writeFile} from "node:fs/promises";
import {join} from "node:path";
const [browser, profile, url, output, widthText, heightText] = process.argv.slice(2);
const width = Number(widthText), height = Number(heightText);
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const child = spawn(browser, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--disable-background-networking", "--disable-extensions", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"],
  {windowsHide: true, stdio: ["ignore", "ignore", "ignore"]});
let socket;
try {
  let port;
  for (let i = 0; i < 100; i++) {
    try { port = (await readFile(join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]; break; } catch {}
    if (child.exitCode !== null) throw new Error(`Owned Edge exited ${child.exitCode}`);
    await delay(100);
  }
  if (!port) throw new Error("Owned Edge debug endpoint unavailable");
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {method: "PUT"})).json();
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  const pending = new Map(); let sequence = 0;
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data), entry = pending.get(message.id);
    if (entry) { pending.delete(message.id); message.error ? entry.reject(new Error(JSON.stringify(message.error))) : entry.resolve(message.result); }
  };
  const send = (method, params={}) => new Promise((resolve,reject) => {
    const id = ++sequence; pending.set(id,{resolve,reject}); socket.send(JSON.stringify({id,method,params}));
  });
  await send("Page.enable"); await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", {width,height,deviceScaleFactor:1,mobile:false});
  await send("Page.navigate", {url});
  let done = false;
  for(let i=0;i<150;i++) {
    const value=await send("Runtime.evaluate",{expression:"document.body?.hasAttribute('data-analysis-smoke')",returnByValue:true});
    if(value.result?.value) {done=true;break;} await delay(100);
  }
  if(!done)throw new Error("Synthetic UI checks timed out");
  await delay(100);
  const dom = await send("Runtime.evaluate",{expression:"document.documentElement.outerHTML",returnByValue:true});
  const shot = await send("Page.captureScreenshot",{format:"png",captureBeyondViewport:false});
  await writeFile(`${output}.html`,dom.result.value,"utf8"); await writeFile(`${output}.png`,Buffer.from(shot.data,"base64"));
  process.stdout.write(dom.result.value);
  // Closing the browser may close the target WebSocket before a command reply.
  // Do not await an acknowledgement on that disappearing connection.
  socket.send(JSON.stringify({id:++sequence,method:"Browser.close",params:{}}));
  await delay(300);
} finally { if(socket) socket.close(); if(child.exitCode === null) child.kill(); }
process.exit(0);
