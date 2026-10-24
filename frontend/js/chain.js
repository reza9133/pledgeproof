// Thin wrapper around genlayer-js: reads need no wallet, writes are signed by the EIP-6963 wallet.
// The SDK is self-hosted (js/vendor/genlayer.js, rebuild with tools/build-vendor.sh), so the site has no CDN dependency.
const C = window.PP_CONFIG;
let lib = null, reader = null, writer = null, prov = null;

async function load() {
  if (lib) return lib;
  const m = await import("./vendor/genlayer.js");
  // A copy of the chain that points at the RPC from config.js (the SDK mutates the chain it is given).
  const chain = { ...m.studionet, rpcUrls: { default: { http: [C.rpc || m.studionet.rpcUrls.default.http[0]] } } };
  lib = { createClient: m.createClient, chain };
  return lib;
}

export const ready = () => /^0x[0-9a-fA-F]{40}$/.test(C.contract || "");
export const txUrl = (hash) => (C.explorerTx && /^0x[0-9a-fA-F]+$/.test(hash || "") ? C.explorerTx.replace("{hash}", hash) : "");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------- reads, with a visible "stale" fallback ---------- */
// Studio RPC can hiccup ("unknown RPC error"): retry with growing delays. If every try fails, serve the last good answer
// for the same call from this tab, and remember that we did so (staleSince) so the page can say the data may be old.
const ser = (v) => JSON.stringify(v, (_, x) => (typeof x === "bigint" ? x.toString() : x));
const ck = (fn, args) => "pp2:" + fn + ":" + ser(args);
const stale = new Map(); // cache key -> when (ms) the saved answer was stored
const emitStale = () => window.dispatchEvent(new Event("pp-stale"));
export const staleSince = () => (stale.size ? Math.min(...stale.values()) : 0);

export async function read(fn, args = []) {
  let err; const key = ck(fn, args);
  for (let i = 0; i < 5; i++) {
    try {
      const { createClient, chain } = await load();
      reader ||= createClient({ chain, endpoint: C.rpc });
      const v = await reader.readContract({ address: C.contract, functionName: fn, args });
      try { sessionStorage.setItem(key, ser({ t: Date.now(), v })); } catch {}
      if (stale.delete(key)) emitStale();
      return v;
    } catch (e) { err = e; if (contractError(e)) throw e; if (i < 4) await sleep(400 * (i + 1) ** 2); }
  }
  try {
    const old = JSON.parse(sessionStorage.getItem(key) || "null");
    if (old && typeof old.t === "number" && "v" in old) { stale.set(key, old.t); emitStale(); return old.v; }
  } catch {}
  throw err;
}

// Run fn over items with limited concurrency; failed items are skipped and counted.
export async function pool(items, fn, n = 2) {
  const out = new Array(items.length); let k = 0, failed = 0;
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
    while (k < items.length) { const i = k++; try { out[i] = await fn(items[i]); } catch { failed++; } }
  }));
  return { values: out.filter((v) => v !== undefined), failed };
}

/* ---------- clock ---------- */
// The contract judges deadlines with the transaction's timestamp, not with the visitor's clock. A visitor's device clock can
// be wrong, so we measure it against the clock of the web server that served this page (same-origin response: its Date
// header is always readable). If that is not possible (file://, offline) the clock stays "unverified" and the UI is lenient.
export const clock = { offset: 0, verified: false, source: "device", skew: 0 }; // skew > 0: the device clock is behind
export const now = () => Math.floor(Date.now() / 1000) + clock.offset;
let clockP = null;
export function syncClock() {
  return (clockP ||= (async () => {
    const ctl = typeof AbortController === "function" ? new AbortController() : null, to = setTimeout(() => ctl?.abort(), 4000);
    try { // 1) the site's own server
      const t0 = Date.now();
      const res = await fetch("assets/logo.svg?_=" + t0 + Math.random().toString(36).slice(2, 6), { method: "HEAD", cache: "no-store", signal: ctl?.signal });
      const t1 = Date.now(), d = Date.parse(res.headers.get("date") || ""), age = Number(res.headers.get("age") || 0);
      if (Number.isFinite(d)) {
        const skew = Math.round((d + 500 + (Number.isFinite(age) ? age * 1000 : 0) - (t0 + t1) / 2) / 1000); // Date has 1 s resolution
        clock.skew = skew; clock.verified = true; clock.source = "site";
        if (Math.abs(skew) > 30) clock.offset = skew; // ignore small noise
        return clock;
      }
    } catch {} finally { clearTimeout(to); }
    try { // 2) fallback: the newest block can only be older than "now", so a device clock that is behind it is surely wrong
      const r = await fetch(C.rpc, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_getBlockByNumber", params: ["latest", false] }) });
      let ts = Number((await r.json())?.result?.timestamp); if (ts > 1e11) ts = Math.floor(ts / 1000);
      const local = Math.floor(Date.now() / 1000);
      if (Number.isFinite(ts) && ts > 1.6e9 && ts < 4e9 && ts > local + 60) { clock.skew = clock.offset = ts - local; clock.source = "block"; }
    } catch {}
    return clock;
  })());
}

/* ---------- wallet ---------- */
const hexChain = () => "0x" + C.chainId.toString(16);
const chainOf = (p) => p.request({ method: "eth_chainId" }).then((x) => String(x).toLowerCase(), () => "");

// Make the wallet use the GenLayer network. A refusal (code 4001) is passed on instead of opening a second prompt.
export async function ensureNetwork(provider) {
  const chainId = hexChain();
  if ((await chainOf(provider)) === chainId) return;
  try {
    await provider.request({ method: "wallet_switchEthereumChain", params: [{ chainId }] });
  } catch (e) {
    if (e?.code === 4001) throw e;
    await provider.request({
      method: "wallet_addEthereumChain",
      params: [{
        chainId, chainName: "GenLayer Studio Network", rpcUrls: [C.rpc],
        nativeCurrency: { name: "GEN Token", symbol: "GEN", decimals: 18 }, blockExplorerUrls: [C.explorer],
      }],
    });
    try { await provider.request({ method: "wallet_switchEthereumChain", params: [{ chainId }] }); } catch (e2) { if (e2?.code === 4001) throw e2; }
  }
  const after = await chainOf(provider);
  if (after && after !== chainId) throw new Error("Switch your wallet to the GenLayer Studio network (chain id " + C.chainId + ") and try again.");
}

export function dropWallet() { writer = null; prov = null; }

export async function useWallet(account, provider) {
  const { createClient, chain } = await load();
  prov = provider;
  writer = createClient({ chain, endpoint: C.rpc, account, provider });
}

const REVERT = /\[(EXPECTED|EXTERNAL|TRANSIENT|LLM_ERROR)\][^"'\\\n]*/;
const flat = (x, depth = 0) => {
  if (x == null || depth > 4) return "";
  if (typeof x === "string") return x;
  if (typeof x !== "object") return String(x);
  let t = "";
  if (x instanceof Error) t += [x.message, x.shortMessage, x.details].filter(Boolean).join(" ") + " " + flat(x.cause, depth + 1);
  try { t += " " + JSON.stringify(x, (_, v) => (typeof v === "bigint" ? v.toString() : v)); } catch {}
  return t;
};
export const contractError = (x) => { const m = REVERT.exec(flat(x)); return m ? m[0].trim() : ""; };

// Mirrors scripts/live_e2e.py: read only the transaction's own outcome.
export function outcome(r) {
  if (!r || typeof r !== "object") return { ok: null, error: "" };
  const error = contractError(r);
  const top = r.tx_execution_result_name || r.txExecutionResultName;
  const leaders = r.consensus_data?.leader_receipt;
  const lead = Array.isArray(leaders) ? leaders.filter((x) => x && x.mode !== "validator") : [];
  let ex = [];
  if (typeof top === "string" && top) ex = [top.toUpperCase()];
  else if (lead.length && typeof lead[lead.length - 1].execution_result === "string") ex = [lead[lead.length - 1].execution_result.toUpperCase()];
  const res = String(r.result_name || "").toUpperCase(), st = String(r.status_name || "").toUpperCase();
  if (ex.some((e) => e.includes("ERROR"))) return { ok: false, error: error || "execution error" };
  if (["DISAGREE", "TIMEOUT", "NO_MAJORITY", "MAJORITY_DISAGREE", "DETERMINISTIC_VIOLATION"].includes(res)) return { ok: false, error: error || "consensus result " + res };
  if (["UNDETERMINED", "CANCELED", "LEADER_TIMEOUT", "VALIDATORS_TIMEOUT"].includes(st)) return { ok: false, error: error || "status " + st };
  if (ex.some((e) => e.includes("SUCCESS") || e.includes("RETURN"))) return { ok: true, error: "" };
  return { ok: null, error };
}

// An accepted transaction is provisional: validators can still be challenged, and a payment emitted by the contract is only
// delivered when the transaction is FINALIZED. write() resolves at ACCEPTED (the outcome is known); callers that report
// "done" or money moved must await result.finalized, which resolves { ok, receipt } or { ok: false, timedOut } at FINALIZED.
export async function write(fn, args = [], value = 0n, onHash) {
  if (!writer) throw new Error("Connect a wallet first.");
  await ensureNetwork(prov); // throws a clear error instead of sending the transaction on the wrong network
  const hash = await writer.writeContract({ address: C.contract, functionName: fn, args, value });
  onHash?.(hash);
  const receipt = await writer.waitForTransactionReceipt({ hash, status: "ACCEPTED", interval: 3000, retries: 400 });
  const o = outcome(receipt);
  if (o.ok === false) { const e = new Error(o.error); e.hash = hash; throw e; }
  const w = writer;
  const finalized = w.waitForTransactionReceipt({ hash, status: "FINALIZED", interval: 5000, retries: 1200 })
    .then((r) => ({ ok: outcome(r).ok !== false, receipt: r, timedOut: false }), () => ({ ok: false, receipt: null, timedOut: true }));
  return { hash, receipt, unconfirmed: o.ok === null, finalized };
}

// Payment evidence for a campaign: the vault's own payout ledger (what was emitted, and whether its balance proved it left).
export const payouts = (id) => read("list_payouts", [BigInt(id), 0n, 100n]);
export const ledger = () => read("get_ledger", []);
