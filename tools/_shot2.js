/**
 * 按 CSS 选择器逐元素截图（无头 Chrome + CDP，零依赖）。
 *
 * 用法：
 *   node _shot2.js <file:///abs/path.html> <outdir> <sel...>
 * 或：
 *   node _shot2.js <file:///abs/path.html> <outdir> --sections
 *      --sections = 逐个 `.sec` 截图，文件名 sec-00.png …
 */
const http = require("http");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");

const [, , URL_, OUTDIR, ...REST] = process.argv;
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9333 + Math.floor(Math.random() * 400);

function get(p) {
  return new Promise((res, rej) => {
    http.get({ host: "127.0.0.1", port: PORT, path: p }, (r) => {
      let d = "";
      r.on("data", (c) => (d += c));
      r.on("end", () => res(JSON.parse(d)));
    }).on("error", rej);
  });
}

(async () => {
  fs.mkdirSync(OUTDIR, { recursive: true });
  const chrome = spawn(CHROME, [
    "--headless=new", "--disable-gpu", "--hide-scrollbars",
    `--remote-debugging-port=${PORT}`,
    "--window-size=900,1400",
    "--no-first-run", "--no-default-browser-check",
    "--user-data-dir=" + path.join(require("os").tmpdir(), "cdp" + PORT),
    "about:blank",
  ], { stdio: "ignore" });

  let tabs = null;
  for (let i = 0; i < 60; i++) {
    try { tabs = await get("/json/list"); if (tabs && tabs.length) break; } catch (e) {}
    await new Promise((r) => setTimeout(r, 250));
  }
  if (!tabs) { console.error("Chrome 未就绪"); chrome.kill(); process.exit(1); }
  const target = tabs.find((t) => t.type === "page");
  const WS = target.webSocketDebuggerUrl;

  // 极简 WebSocket 客户端（Node 22 内置 WebSocket）
  const ws = new WebSocket(WS);
  await new Promise((r) => (ws.onopen = r));
  let id = 0; const waits = new Map();
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && waits.has(m.id)) { waits.get(m.id)(m); waits.delete(m.id); }
  };
  const send = (method, params = {}) => new Promise((res) => {
    const i = ++id; waits.set(i, res);
    ws.send(JSON.stringify({ id: i, method, params }));
  });

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Page.navigate", { url: URL_ });
  await new Promise((r) => setTimeout(r, 2500));

  let sels;
  if (REST[0] === "--sections") {
    const r = await send("Runtime.evaluate", {
      expression: `JSON.stringify([...document.querySelectorAll('.sec')].map((e,i)=>[i,(e.querySelector('h3')||{}).textContent||'']))`,
      returnByValue: true,
    });
    const list = JSON.parse(r.result.result.value);
    sels = list;
    console.log("节数", list.length);
  } else {
    sels = REST.map((s, i) => [i, s]);
  }

  for (const [i, cap] of (sels || [])) {
    let r;
    if (REST[0] === "--sections") {
      r = await send("Runtime.evaluate", {
        expression: `(()=>{const e=document.querySelectorAll('.sec')[${i}];const b=e.getBoundingClientRect();return JSON.stringify({x:b.x+scrollX,y:b.y+scrollY,w:b.width,h:b.height})})()`,
        returnByValue: true,
      });
    } else {
      r = await send("Runtime.evaluate", {
        expression: `(()=>{const e=document.querySelector(${JSON.stringify(cap)});if(!e)return 'null';const b=e.getBoundingClientRect();return JSON.stringify({x:b.x+scrollX,y:b.y+scrollY,w:b.width,h:b.height})})()`,
        returnByValue: true,
      });
    }
    if (!r.result.result.value || r.result.result.value === "null") { console.log("跳过", cap); continue; }
    const b = JSON.parse(r.result.result.value);
    if (b.w < 2 || b.h < 2) { console.log("零尺寸", cap); continue; }
    const shot = await send("Page.captureScreenshot", {
      format: "png",
      clip: { x: b.x, y: b.y, width: b.w, height: Math.min(b.h, 4000), scale: 1 },
      captureBeyondViewport: true,
    });
    const f = path.join(OUTDIR, REST[0] === "--sections"
      ? `sec-${String(i).padStart(2, "0")}.png`
      : `sel-${i}.png`);
    fs.writeFileSync(f, Buffer.from(shot.result.data, "base64"));
    console.log("写出", f, `${Math.round(b.w)}x${Math.round(b.h)}`, String(cap).slice(0, 40));
  }

  ws.close(); chrome.kill();
  process.exit(0);
})();
