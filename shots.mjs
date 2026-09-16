// Capture dashboard thumbnails with headless Chrome over the DevTools protocol.
//
// Every request whose method is not GET/HEAD/OPTIONS is failed before it leaves
// the browser, so apps that save on load (the task manager API, Supabase apps)
// cannot change production data while being photographed.
//
//   node shots.mjs <targets.json> <outDir>
//   targets.json: [{ "id": "...", "url": "https://... or file:///..." }]
//   prints one JSON line per target: { id, loaded, blocked: [...], error? }

import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const WIDTH = 1280;
const HEIGHT = 800;
const LOAD_TIMEOUT_MS = 25000;
const SETTLE_MS = 3500; // charts, web fonts and client-side data fetches
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function launchChrome() {
  const profile = mkdtempSync(join(tmpdir(), "hub-shots-"));
  const proc = spawn(CHROME, [
    "--headless=new",
    "--remote-debugging-port=0",
    `--user-data-dir=${profile}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--hide-scrollbars",
    "--mute-audio",
    `--window-size=${WIDTH},${HEIGHT}`,
    "about:blank",
  ], { stdio: "ignore" });

  const portFile = join(profile, "DevToolsActivePort");
  for (let i = 0; i < 150; i++) {
    const lines = existsSync(portFile) ? readFileSync(portFile, "utf8").trim().split("\n") : [];
    if (lines.length === 2) return { proc, profile, wsUrl: `ws://127.0.0.1:${lines[0]}${lines[1]}` };
    await sleep(100);
  }
  proc.kill();
  throw new Error("Chrome did not open a DevTools port");
}

function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  const pending = new Map();
  const listeners = new Set();
  let seq = 0;

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    } else if (msg.method) {
      for (const fn of listeners) fn(msg);
    }
  };

  return {
    opened: new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; }),
    send(method, params = {}, sessionId) {
      return new Promise((resolve, reject) => {
        const id = ++seq;
        pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ id, method, params, sessionId }));
      });
    },
    on: (fn) => listeners.add(fn),
    off: (fn) => listeners.delete(fn),
    close: () => ws.close(),
  };
}

async function capture(cdp, outDir, { id, url }) {
  const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
  const blocked = [];

  const guard = (msg) => {
    if (msg.sessionId !== sessionId || msg.method !== "Fetch.requestPaused") return;
    const { requestId, request } = msg.params;
    if (SAFE_METHODS.has(request.method)) {
      cdp.send("Fetch.continueRequest", { requestId }, sessionId).catch(() => {});
    } else {
      blocked.push(`${request.method} ${request.url}`);
      cdp.send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }, sessionId).catch(() => {});
    }
  };
  cdp.on(guard);

  try {
    // The guard must be active before the first request of the page goes out.
    await cdp.send("Fetch.enable", { patterns: [{ urlPattern: "*" }] }, sessionId);
    await cdp.send("Page.enable", {}, sessionId);
    await cdp.send("Emulation.setDeviceMetricsOverride",
      { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: false }, sessionId);

    const loaded = new Promise((resolve) => {
      const onLoad = (msg) => {
        if (msg.sessionId === sessionId && msg.method === "Page.loadEventFired") {
          cdp.off(onLoad);
          resolve(true);
        }
      };
      cdp.on(onLoad);
      setTimeout(() => { cdp.off(onLoad); resolve(false); }, LOAD_TIMEOUT_MS);
    });
    await cdp.send("Page.navigate", { url }, sessionId);
    const didLoad = await loaded;
    await sleep(SETTLE_MS);

    const { data } = await cdp.send("Page.captureScreenshot", { format: "png" }, sessionId);
    writeFileSync(join(outDir, `${id}.png`), Buffer.from(data, "base64"));
    return { id, loaded: didLoad, blocked };
  } finally {
    cdp.off(guard);
    await cdp.send("Target.closeTarget", { targetId }).catch(() => {});
  }
}

async function main() {
  const [targetsPath, outDir] = process.argv.slice(2);
  if (!targetsPath || !outDir) throw new Error("usage: node shots.mjs <targets.json> <outDir>");
  const targets = JSON.parse(readFileSync(targetsPath, "utf8"));

  const chrome = await launchChrome();
  const cdp = connect(chrome.wsUrl);
  try {
    await cdp.opened;
    for (const target of targets) {
      let result;
      try {
        result = await capture(cdp, outDir, target);
      } catch (err) {
        result = { id: target.id, loaded: false, blocked: [], error: String(err.message || err) };
      }
      process.stdout.write(JSON.stringify(result) + "\n");
    }
  } finally {
    cdp.close();
    chrome.proc.kill();
    await sleep(500);
    try { rmSync(chrome.profile, { recursive: true, force: true }); } catch {}
  }
}

main().catch((err) => {
  process.stderr.write(String(err.stack || err) + "\n");
  process.exit(1);
});
