import * as chain from "./chain.js";

const C = window.PP_CONFIG, $ = (s, r = document) => r.querySelector(s);
const page = document.body.dataset.page;
const safe = (f) => { try { return f(); } catch { return null; } };
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- helpers ---------- */
const N = (x) => { try { return BigInt(x ?? 0); } catch { return 0n; } };
const E18 = 10n ** 18n;
const gen = (w, d = 4) => { w = N(w); const f = (w % E18).toString().padStart(18, "0").slice(0, d).replace(/0+$/, ""); return (w / E18).toLocaleString() + (f ? "." + f : ""); };
/* Persian/Arabic digits and separators are accepted: "۱٫۵", "1,5" and "1.5" all mean one and a half; "1,000" means one thousand. */
const normNum = (t) => {
  let x = String(t ?? "").trim().replace(/[۰-۹]/g, (d) => d.charCodeAt(0) - 0x6f0).replace(/[٠-٩]/g, (d) => d.charCodeAt(0) - 0x660).replace(/[\s_٬]/g, "").replace(/٫/g, ".");
  if (!x.includes(".") && x.includes(",")) x = /^[1-9]\d{0,2}(,\d{3})+$/.test(x) ? x.replace(/,/g, "") : x.replace(/^(\d+),(\d+)$/, "$1.$2");
  return x;
};
const parseGen = (t) => { const m = normNum(t).match(/^(\d*)(?:\.(\d{1,18}))?$/); return m && (m[1] || m[2]) ? BigInt(m[1] || "0") * E18 + BigInt((m[2] || "").padEnd(18, "0")) : null; };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const short = (a) => (a ? a.slice(0, 6) + "…" + a.slice(-4) : "");
const when = (ts) => new Date(Number(ts) * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
/* chain.now() is the device clock corrected against the web server's clock (see chain.js), because the contract uses the transaction's time */
const nowSec = () => chain.now();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const httpsOnly = (u) => (/^https:\/\//i.test(u) ? u : "#");
const same = (a, b) => !!a && !!b && a.toLowerCase() === b.toLowerCase();

/* transaction hash: short link to the explorer (if config.js has explorerTx) plus a copy button */
function txBits(hash) {
  const f = document.createDocumentFragment(), url = chain.txUrl(hash);
  f.append(" · tx ");
  const el = document.createElement(url ? "a" : "code");
  if (url) { el.href = url; el.target = "_blank"; el.rel = "noopener noreferrer"; }
  el.textContent = short(hash) + (url ? " ↗" : ""); el.title = hash;
  const b = document.createElement("button");
  b.type = "button"; b.className = "btn ghost mini"; b.textContent = "Copy hash";
  b.onclick = () => navigator.clipboard?.writeText(hash).then(() => (b.textContent = "Copied"), () => (b.textContent = "Copy failed"));
  f.append(el, " ", b); return f;
}
const say = (el, msg, bad, hash) => { el.hidden = !msg; el.textContent = msg || ""; el.classList.toggle("bad", !!bad); if (msg && hash) el.append(txBits(hash)); };

/* ---------- theme: light / dim / dark ---------- */
const setTheme = (t) => {
  document.documentElement.dataset.theme = t;
  safe(() => localStorage.setItem("pp-theme", t));
  document.querySelectorAll(".themes button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.t === t));
  window.dispatchEvent(new Event("pp-theme"));
};
document.documentElement.dataset.theme = safe(() => localStorage.getItem("pp-theme")) || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");

/* ---------- shared header and footer ---------- */
const links = [["index", "Home", "index.html"], ["campaigns", "Campaigns", "campaigns.html"], ["my", "My pledges", "my.html"], ["launch", "Launch", "launch.html"], ["how", "How it works", "how.html"]];
document.body.insertAdjacentHTML("afterbegin", `<header><div class="wrap">
<a class="brand" href="index.html"><img src="assets/logo.svg" alt="">PledgeProof</a>
<nav aria-label="Main">${links.map(([k, n, h]) => `<a href="${h}" ${k === page || (k === "campaigns" && page === "campaign") ? 'aria-current="page"' : ""}>${n}</a>`).join("")}</nav>
<div class="themes" role="group" aria-label="Theme">${["light", "dim", "dark"].map((t) => `<button data-t="${t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div>
<button class="btn" id="wbtn">Connect wallet</button><button class="menu" id="menu" aria-label="Menu" aria-expanded="false"><span></span><span></span><span></span></button></div></header>
<dialog id="wd"><div id="acct" hidden><h3>Wallet connected</h3><p><code id="aaddr"></code></p><div class="row"><button class="btn ghost" id="acopy">Copy address</button><button class="btn ghost" id="aswitch">Switch wallet</button><button class="btn" id="adisc">Disconnect</button></div></div><div id="pick"><h3>Choose a wallet</h3><div id="wl"></div><p class="note" id="wn">No wallet detected. Install a browser wallet and reload.</p></div><button class="btn ghost" style="margin-top:14px" onclick="this.closest('dialog').close()">Close</button></dialog>`);
document.body.insertAdjacentHTML("beforeend", `<footer><div class="wrap"><span class="built"><span>Built on</span><img class="gl" src="assets/genlayer-wordmark.svg" alt="GenLayer"></span>
<span class="social">${chain.ready() ? `<a href="${C.explorer}/address/${C.contract}" target="_blank" rel="noopener">Contract ${short(C.contract)}</a>` : ""}<a href="${C.github}" target="_blank" rel="noopener">GitHub</a><a href="${C.twitter}" target="_blank" rel="noopener">@amirhp771 on X</a></span></div></footer>`);
document.querySelector("header").insertAdjacentHTML("afterend", `<div class="banner" id="bstale" role="status" hidden><div class="wrap"><span></span><button class="btn ghost mini" type="button">Retry</button></div></div><div class="banner" id="bclock" role="status" hidden><div class="wrap"><span></span></div></div>`);
document.querySelectorAll(".themes button").forEach((b) => (b.onclick = () => setTheme(b.dataset.t)));
setTheme(document.documentElement.dataset.theme);
/* data served from the saved copy (network not answering) is labelled as possibly old */
addEventListener("pp-stale", () => {
  const at = chain.staleSince(), el = $("#bstale");
  el.hidden = !at;
  if (at) $("span", el).textContent = `Showing saved data from ${new Date(at).toLocaleTimeString([], { timeStyle: "short" })}. The network is not answering right now, so what you see may be out of date.`;
});
$("#bstale button").onclick = () => (window.PP.refresh ? window.PP.refresh() : location.reload());
/* pages that compare times: measure the device clock once; show a note when it is far off */
const clockReady = page === "campaign" || page === "launch"
  ? Promise.race([chain.syncClock(), sleep(3000)]).then(() => {
      const k = chain.clock, m = Math.round(Math.abs(k.skew) / 60), el = $("#bclock");
      if (m < 2) return;
      el.hidden = false;
      $("span", el).textContent = k.verified
        ? `Your device clock is about ${m} min ${k.skew > 0 ? "behind" : "ahead of"} the web server's clock. Deadlines and buttons on this page use the corrected time; please fix your system time.`
        : `Your device clock looks at least ${m} min behind the network. Deadlines and buttons use a corrected time, but please check your system time.`;
    })
  : Promise.resolve();

/* ---------- EIP-6963 wallet discovery ---------- */
const wallets = new Map();
window.PP = { provider: null, account: null };
const KEY = "pp-wallet";
addEventListener("eip6963:announceProvider", (e) => {
  wallets.set(e.detail.info.uuid, e.detail); renderWallets();
  if (!PP.account && !PP.busy && safe(() => localStorage.getItem(KEY)) === e.detail.info.rdns) connect(e.detail, true); /* restore session after page change */
});
dispatchEvent(new Event("eip6963:requestProvider"));
function renderWallets() {
  const l = $("#wl"); l.innerHTML = ""; $("#wn").hidden = wallets.size > 0;
  wallets.forEach((w) => {
    const b = document.createElement("button");
    b.className = "wal"; b.innerHTML = `<img alt="" src="${esc(w.info.icon)}"><b>${esc(w.info.name)}</b>`;
    b.onclick = () => connect(w); l.append(b);
  });
}
const label = () => ($("#wbtn").textContent = PP.account ? short(PP.account) : "Connect wallet");
async function connect(w, silent = false) {
  const note = $("#wn");
  PP.busy = true;
  try {
    const [acc] = await w.provider.request({ method: silent ? "eth_accounts" : "eth_requestAccounts" });
    if (!acc) { safe(() => localStorage.removeItem(KEY)); return; }
    if (!silent) { try { await chain.ensureNetwork(w.provider); } catch {} } /* a declined switch does not block connecting; sending a transaction re-checks the network */
    await chain.useWallet(acc, w.provider);
    safe(() => localStorage.setItem(KEY, w.info.rdns));
    PP.provider = w.provider; PP.account = acc; label(); $("#wd").close();
    if (PP.off) PP.off();
    const onAcc = async (a) => {
      if (!a[0]) return disconnect(false);
      PP.account = a[0]; label(); await chain.useWallet(PP.account, w.provider);
      dispatchEvent(new Event("pp-connected"));
    };
    w.provider.on?.("accountsChanged", onAcc);
    PP.off = () => { w.provider.removeListener?.("accountsChanged", onAcc); PP.off = null; };
    dispatchEvent(new Event("pp-connected"));
  } catch (err) {
    if (silent) return;
    note.hidden = false;
    note.textContent = err?.code === 4001 ? "Connection was rejected in the wallet." : "Could not connect: " + (err?.shortMessage || err?.message || err);
  } finally { PP.busy = false; }
}
async function disconnect(revoke = true) {
  const pr = PP.provider;
  safe(() => localStorage.removeItem(KEY));
  if (PP.off) PP.off();
  if (revoke && pr) { try { await pr.request({ method: "wallet_revokePermissions", params: [{ eth_accounts: {} }] }); } catch {} }
  PP.provider = null; PP.account = null; chain.dropWallet(); label();
  if ($("#wd").open) $("#wd").close();
  dispatchEvent(new Event("pp-connected"));
}
const showWd = (pick) => { $("#acct").hidden = !PP.account || pick; $("#pick").hidden = !!PP.account && !pick; $("#aaddr").textContent = PP.account || ""; if (pick) renderWallets(); };
$("#wbtn").onclick = () => { renderWallets(); showWd(false); $("#wd").showModal(); };
$("#adisc").onclick = () => disconnect(true);
$("#aswitch").onclick = () => showWd(true);
$("#acopy").onclick = () => navigator.clipboard?.writeText(PP.account).then(() => ($("#acopy").textContent = "Copied"), () => {});
$("#wd").addEventListener("close", () => ($("#acopy").textContent = "Copy address"));

/* ---------- 3D vault ring (three.js, self-hosted, purely decorative) ---------- */
/* Loaded only when it can be seen; if the file, WebGL or the GPU is missing the page works the same without it. */
const loadScript = (src) => new Promise((ok, no) => { const el = document.createElement("script"); el.src = src; el.onload = ok; el.onerror = () => no(new Error("could not load " + src)); setTimeout(() => no(new Error("timed out: " + src)), 10000); document.head.append(el); });
const stage = $("#stage");
function startStage() {
  const T = THREE, r = new T.WebGLRenderer({ canvas: stage, alpha: true, antialias: true });
  const sc = new T.Scene(), cam = new T.PerspectiveCamera(45, 1, .1, 100); cam.position.z = 9;
  const root = new T.Group(); sc.add(root);
  const col = () => new T.Color(getComputedStyle(document.documentElement).getPropertyValue("--acc").trim());
  const mats = [], segs = [.55, .3, .15]; let start = 0;
  segs.forEach((s) => {
    const m = new T.MeshStandardMaterial({ color: col(), metalness: .5, roughness: .3, emissive: col(), emissiveIntensity: .15 });
    const mesh = new T.Mesh(new T.TorusGeometry(2.6, .22, 24, 90, s * Math.PI * 2 - .18), m); mesh.rotation.z = start; start += s * Math.PI * 2; root.add(mesh); mats.push(m);
  });
  const polys = [[[44.26,32.35],[27.72,67.12],[43.29,74.9],[0,91.93],[44.26,0]], [[53.5,32.35],[70.04,67.12],[54.47,74.9],[97.76,91.93],[53.5,0]], [[48.64,43.78],[58.33,62.94],[48.64,67.69],[39.47,62.92]]];
  const core = new T.Group(), brass = new T.MeshStandardMaterial({ color: 0xd9a441, metalness: .85, roughness: .22 });
  polys.forEach((pts) => { const sh = new T.Shape(); pts.forEach(([x, y], i) => (i ? sh.lineTo(x - 48.88, 46 - y) : sh.moveTo(x - 48.88, 46 - y)));
    const g = new T.ExtrudeGeometry(sh, { depth: 14, bevelEnabled: true, bevelSize: 1.2, bevelThickness: 1.2, bevelSegments: 2 }); g.translate(0, 0, -7);
    core.add(new T.Mesh(g, brass)); });
  core.scale.setScalar(.034); root.add(core);
  const pn = 700, pa = new Float32Array(pn * 3); for (let i = 0; i < pn; i++) { const r0 = 5 + Math.random() * 9, a = Math.random() * 6.283, b = Math.acos(2 * Math.random() - 1); pa.set([r0 * Math.sin(b) * Math.cos(a), r0 * Math.sin(b) * Math.sin(a) * .6, r0 * Math.cos(b)], i * 3); }
  const pg = new T.BufferGeometry(); pg.setAttribute("position", new T.BufferAttribute(pa, 3));
  const dust = new T.Points(pg, new T.PointsMaterial({ color: col(), size: .035, transparent: true, opacity: .7 })); sc.add(dust); mats.push(dust.material);
  const ring2 = new T.Mesh(new T.TorusGeometry(3.6, .02, 8, 120), new T.MeshBasicMaterial({ color: col(), transparent: true, opacity: .5 })); ring2.rotation.x = 1.2; root.add(ring2); mats.push(ring2.material);
  sc.add(new T.AmbientLight(0xffffff, .6)); const pl = new T.PointLight(0xffffff, 1.4); pl.position.set(5, 5, 8); sc.add(pl);
  addEventListener("pp-theme", () => mats.forEach((m) => { m.color.copy(col()); m.emissive?.copy(col()); }));
  const size = () => { const w = stage.clientWidth, h = stage.clientHeight; r.setSize(w, h, false); r.setPixelRatio(Math.min(devicePixelRatio, 2)); cam.aspect = w / h; cam.updateProjectionMatrix(); root.position.x = w > 900 ? 3 : 0; };
  size(); addEventListener("resize", size);
  let mx = 0, my = 0; addEventListener("pointermove", (e) => { mx = e.clientX / innerWidth - .5; my = e.clientY / innerHeight - .5; });
  let on = true, raf = 0;
  const loop = (t) => {
    raf = 0; if (!on || document.hidden) return;
    root.rotation.y += (mx * .8 - root.rotation.y) * .04; root.rotation.x += (my * .6 + .3 - root.rotation.x) * .04;
    root.children.slice(0, 3).forEach((m, i) => (m.rotation.z += .002 * (i + 1)));
    core.rotation.y = Math.sin(t * .0007) * .9; core.position.y = Math.sin(t * .0011) * .12; dust.rotation.y = t * .00005; mats[1].emissiveIntensity = .15 + .12 * Math.sin(t * .002);
    r.render(sc, cam); raf = requestAnimationFrame(loop);
  };
  const kick = () => { if (!raf && on && !document.hidden) raf = requestAnimationFrame(loop); };
  if ("IntersectionObserver" in window) new IntersectionObserver(([e]) => { on = e.isIntersecting; kick(); }).observe(stage);
  document.addEventListener("visibilitychange", kick); kick();
}
if (stage && !reduced) {
  (async () => {
    try { if (!window.THREE) await loadScript("js/vendor/three.min.js"); startStage(); } catch { stage.remove(); }
  })();
}
/* card tilt (delegated, so cards rendered later work too) */
if (!reduced) {
  document.addEventListener("pointermove", (e) => {
    const c = e.target.closest?.(".card.tilt"); if (!c) return; const b = c.getBoundingClientRect();
    c.style.transform = `perspective(700px) rotateY(${((e.clientX - b.left) / b.width - .5) * 8}deg) rotateX(${-((e.clientY - b.top) / b.height - .5) * 8}deg)`;
  });
  document.addEventListener("pointerout", (e) => { const c = e.target.closest?.(".card.tilt"); if (c && !c.contains(e.relatedTarget)) c.style.transform = ""; });
}

/* ---------- chain data ---------- */
const getCampaign = (id) => chain.read("get_campaign", [BigInt(id)]);
const notReady = (el) => { el.innerHTML = `<p class="note">The contract address is not set. Add it to js/config.js.</p>`; };
const failRead = (el, e, retry) => { el.innerHTML = `<p class="note">Could not read the contract right now (${esc(e?.shortMessage || e?.message || e)}). <button class="btn ghost" id="retry" style="padding:4px 14px">Retry</button></p>`; const b = el.querySelector("#retry"); if (b) b.onclick = retry || (() => location.reload()); };

const card = (c) => {
  const ms = c.milestones || [], goal = N(c.goal), raised = N(c.raised);
  const pct = goal > 0n ? Number((raised * 100n) / goal) : 0;
  return `<a class="card tilt" href="campaign.html?id=${c.id}" style="text-decoration:none;display:block"><span class="pill ${esc(c.status)}">${esc(c.status)}</span>
<h3 style="margin-top:12px">${esc(c.title)}</h3>
<div class="bar" role="img" aria-label="Milestones approved">${ms.map((m) => `<i style="flex:1;opacity:${m.state === "passed" ? 1 : m.state === "pending" ? .55 : .15}"></i>`).join("")}</div>
<small>${gen(raised)} of ${gen(goal)} GEN pledged (${pct}%) · ${c.backer_count} backers</small></a>`;
};

/* home: live counter */
const stats = $("#stats");
if (stats) {
  if (!chain.ready()) stats.hidden = true;
  else chain.read("campaign_count").then((n) => { stats.textContent = `${N(n)} campaign${N(n) === 1n ? "" : "s"} on Studionet so far`; stats.hidden = false; }).catch(() => (stats.hidden = true));
}

/* campaigns list */
const list = $("#campaigns");
if (list) {
  let all = [], filter = "";
  const draw = () => {
    const shown = all.filter((c) => !filter || c.status === filter);
    list.innerHTML = shown.length ? shown.map(card).join("") : `<p class="note">${all.length ? "No campaigns with this status." : "No campaigns yet. Be the first to launch one."}</p>`;
  };
  document.querySelectorAll("#filters button").forEach((b) => (b.onclick = () => {
    filter = b.dataset.s; document.querySelectorAll("#filters button").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw();
  }));
  const loadList = async () => {
    if (!chain.ready()) return notReady(list);
    list.innerHTML = `<p class="note">Loading campaigns…</p>`;
    try {
      const ids = (await chain.read("list_campaign_ids", [""])).map(Number).sort((a, b) => b - a).slice(0, 48);
      const r = await chain.pool(ids, getCampaign);
      if (ids.length && !r.values.length) throw new Error("no campaign could be loaded");
      all = r.values; draw();
      if (r.failed) list.insertAdjacentHTML("beforeend", `<p class="note full">${r.failed} campaign(s) could not be loaded. <button class="btn ghost" id="retry" style="padding:4px 14px">Retry</button></p>`), ($("#retry").onclick = loadList);
    } catch (e) { failRead(list, e, loadList); }
  };
  PP.refresh = loadList; loadList();
}

/* ---------- campaign detail ---------- */
const detail = $("#detail");
if (detail) {
  const rawId = new URLSearchParams(location.search).get("id"), id = /^\d+$/.test(rawId ?? "") ? Number(rawId) : -1;
  const tx = $("#tx");
  const setTx = (msg, bad, hash) => say(tx, msg, bad, hash);
  const TIMED = /window|overdue|delay|deadline|still open|closed|elapsed/i;
  const errText = (e) => {
    const c = chain.contractError(e);
    if (c) return c + (TIMED.test(c) && !chain.clock.verified ? " (Time rules are judged by the network clock; check that your device clock is right.)" : "");
    return e?.code === 4001 || /user (rejected|denied)/i.test(e?.shortMessage || e?.message || "") ? "You rejected the request in your wallet." : e?.shortMessage || e?.message || String(e);
  };
  const effDue = (c, m) => Math.max(Number(m.due), Number(c.current_since) + 3 * 86400, Number(c.cure_until));

  async function run(name, fn, slow) {
    document.querySelectorAll("#detail button").forEach((b) => (b.disabled = true));
    let hash = "";
    setTx(name + ": confirm in your wallet…");
    try {
      const r = await fn((h) => { hash = h; setTx(name + ": submitted, waiting for validators…" + (slow ? " (this can take a few minutes)" : ""), false, h); });
      setTx(name + ": done.", false, hash || r?.hash);
    } catch (e) { setTx(name + " failed: " + errText(e), true, hash || e?.hash); }
    await render(true);
  }

  let rseq = 0; /* overlapping renders (wallet events, finished transactions): only the newest one may draw */
  async function render(keepTx) {
    if (!chain.ready()) return notReady(detail);
    if (!Number.isInteger(id) || id < 0) { detail.innerHTML = `<p class="note">No campaign selected. <a href="campaigns.html">Browse campaigns</a>.</p>`; return; }
    const rid = ++rseq;
    if (!keepTx) setTx("");
    await clockReady;
    let c, pos = { pledged: "0", refundable_now: "0" }, token = "";
    try { c = await getCampaign(id); } catch (e) { if (rid === rseq) failRead(detail, e, () => render(true)); return; }
    const me = PP.account, isCreator = same(me, c.creator), ms = c.milestones;
    if (rid !== rseq) return;
    if (me) { try { pos = await chain.read("get_position", [BigInt(id), me]); } catch {} }
    const cur = ms[c.next_milestone], pledged = N(pos.pledged);
    if (c.status === "active" && isCreator && cur) { try { token = await chain.read("get_proof_token", [BigInt(id), c.next_milestone]); } catch {} }
    if (rid !== rseq) return;
    const t = nowSec();

    const goal = N(c.goal), raised = N(c.raised), pct = goal > 0n ? Math.min(100, Number((raised * 100n) / goal)) : 0;
    const msHtml = ms.map((m, i) => `<li class="ms ${m.state}"><div class="row" style="justify-content:space-between"><b>Milestone ${i + 1} · ${m.bps / 100}%</b><span class="pill ${m.state === "passed" ? "completed" : m.state === "pending" ? "active" : ""}">${esc(m.state)}</span></div>
<p>${esc(m.description)}</p><small>Due ${when(m.due)}${N(m.tranche) > 0n ? ` · paid ${gen(m.tranche)} GEN` : ""}</small>
${m.proof_url ? `<small>Proof: <a href="${esc(httpsOnly(m.proof_url))}" target="_blank" rel="noopener noreferrer">${esc(m.proof_url)}</a></small>` : ""}
${m.verdict ? `<div class="verdict"><b>Last verdict: ${esc(m.verdict)}</b> (confidence ${m.confidence}) · ${m.attempts} review${m.attempts === 1 ? "" : "s"}${m.reason ? `<br>${esc(m.reason)}` : ""}${m.quote ? `<br><i>“${esc(m.quote)}”</i>` : ""}</div>` : ""}</li>`).join("");

    const acts = [];
    if (!me) acts.push(`<p class="note">Connect a wallet to take part in this campaign.</p>`);
    else {
      if (c.status === "funding") {
        const open = t < Number(c.funding_deadline), capped = raised >= N(c.cap);
        if (!isCreator && open && !capped) acts.push(`<div class="row"><input id="amt" inputmode="decimal" placeholder="Amount in GEN (min ${gen(c.min_pledge, 6)})" style="min-width:230px"><button class="btn" id="back">Back this campaign</button></div><small>Room left under the cap: ${gen(N(c.cap) - raised, 6)} GEN</small>`);
        if (pledged > 0n && open) acts.push(`<button class="btn ghost" id="withdraw">Withdraw my pledge (${gen(pledged)} GEN)</button>`);
        if (isCreator && open && !capped) acts.push(`<button class="btn ghost" id="cancel">Cancel campaign</button>`);
        if (!open || capped) acts.push(`<button class="btn" id="close">Close funding</button>`);
      }
      if (c.status === "active" && cur) {
        if (isCreator && t < effDue(c, cur)) acts.push(`<div class="note">Put this proof token on your public proof page, then ${cur.state === "pending" ? "replace" : "submit"} the page URL:<br>${token ? `<code id="tok">${esc(token)}</code> <button class="btn ghost" id="copy" style="padding:4px 12px">Copy</button>` : `<code>could not load the token, press Retry above or reload the page</code>`}</div>
<div class="row"><input id="url" placeholder="https://…" style="min-width:300px"><button class="btn" id="submit">${cur.state === "pending" ? "Replace proof URL" : "Submit proof"}</button></div>${cur.state === "pending" ? `<small>Replacing the URL restarts the one-hour wait for other people's reviews.</small>` : ""}`);
        else if (isCreator) acts.push(`<p class="note">The deadline for this milestone has passed, so a proof can no longer be submitted.</p>`);
        if (cur.state === "pending") {
          const wait = Number(cur.submitted_at) + 3600 - t, early = !isCreator && wait > 0;
          /* the button is locked only when the clock was checked against a server; otherwise the contract decides */
          const hard = early && chain.clock.verified;
          acts.push(`<button class="btn" id="review" ${hard ? "disabled" : ""}>Run validator review</button>${early ? `<small>${hard ? `Others can trigger the review in ${Math.ceil(wait / 60)} min.` : `By your device clock, others must wait about ${Math.ceil(wait / 60)} more min. Your clock could not be checked, so you can still try and the contract will decide.`}</small>` : ""}`);
        }
        const due = effDue(c, cur), grace = cur.state === "pending" ? Number(cur.submitted_at) + 3 * 86400 : 0;
        if (t >= due && t >= grace) acts.push(`<button class="btn ghost" id="default">Declare default (milestone overdue)</button>`);
      }
      if ((c.status === "failed" || c.status === "cancelled") && pledged > 0n) acts.push(`<button class="btn" id="refund">Claim refund (${gen(pos.refundable_now)} GEN)</button>`);
      if (!acts.length) acts.push(`<p class="note">Nothing for you to do on this campaign right now.</p>`);
    }

    detail.innerHTML = `<div class="row" style="justify-content:space-between"><span class="pill ${esc(c.status)}">${esc(c.status)}${c.fail_reason ? " · " + esc(c.fail_reason.replace(/_/g, " ")) : ""}</span><small>Creator <a href="${C.explorer}/address/${esc(c.creator)}" target="_blank" rel="noopener noreferrer">${short(c.creator)}</a>${isCreator ? " (you)" : ""}</small></div>
<h2 style="margin-top:14px">${esc(c.title)}</h2><p>${esc(c.pitch)}</p>
<div class="bar big" role="img" aria-label="Funding progress"><i style="width:${pct}%"></i></div>
<div class="kv"><div><small>Raised</small><b>${gen(raised)} GEN</b></div><div><small>Goal / cap</small><b>${gen(goal)} / ${gen(c.cap)}</b></div><div><small>Backers</small><b>${c.backer_count}</b></div>
<div><small>Released</small><b>${gen(c.released)} GEN</b></div><div><small>Creator bond</small><b>${gen(c.bond)} GEN</b></div><div><small>Funding ends</small><b>${when(c.funding_deadline)}</b></div>
<div><small>Strikes</small><b>${c.strikes} / ${c.max_strikes}</b></div>${me ? `<div><small>Your pledge</small><b>${gen(pledged)} GEN</b></div>` : ""}</div>
<h3 style="margin-top:34px">Milestones</h3><ol class="mslist">${msHtml}</ol>
<h3 style="margin-top:34px">Actions</h3><div class="actions">${acts.join("")}</div>`;

    const on = (sel, fn) => { const el = $(sel, detail); if (el) el.onclick = fn; };
    on("#back", () => {
      const v = parseGen($("#amt").value);
      if (v === null || v <= 0n) return setTx("Enter a valid amount in GEN.", true);
      if (v < N(c.min_pledge)) return setTx(`The minimum pledge is ${gen(c.min_pledge, 6)} GEN.`, true);
      if (v > N(c.cap) - raised) return setTx(`Only ${gen(N(c.cap) - raised, 6)} GEN of room is left under the funding cap.`, true);
      run("Pledge", (h) => chain.write("back", [BigInt(id)], v, h));
    });
    on("#withdraw", () => run("Withdraw", (h) => chain.write("withdraw_pledge", [BigInt(id)], 0n, h)));
    on("#cancel", () => run("Cancel", (h) => chain.write("cancel_campaign", [BigInt(id)], 0n, h)));
    on("#close", () => run("Close funding", (h) => chain.write("close_funding", [BigInt(id)], 0n, h)));
    on("#copy", () => navigator.clipboard?.writeText(token).then(() => setTx("Token copied."), () => setTx("Could not copy automatically: select the token and copy it by hand.", true)));
    on("#submit", () => {
      const u = $("#url").value.trim();
      if (!/^https:\/\//i.test(u)) return setTx("The proof page must be a public https:// URL.", true);
      run("Submit proof", (h) => chain.write("submit_proof", [BigInt(id), u], 0n, h));
    });
    on("#review", () => run("Review", (h) => chain.write("review", [BigInt(id)], 0n, h), true));
    on("#default", () => run("Declare default", (h) => chain.write("declare_default", [BigInt(id)], 0n, h)));
    on("#refund", () => run("Refund", (h) => chain.write("claim_refund", [BigInt(id)], 0n, h)));
  }
  addEventListener("pp-connected", () => render());
  PP.refresh = () => render(true);
  render();
}

/* ---------- launch form ---------- */
const f = $("#launch");
if (f) {
  const SPLIT = [3000, 3000, 4000], DAY = 86400;
  /* same text rules as the contract: invisible direction/control marks are refused, invisible joiners are dropped, whitespace is collapsed, length counts characters */
  const HIDDEN = /[\u0000-\u0008\u000E-\u001B\u007F\u0080-\u0084\u0086-\u009F\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/;
  const norm = (x) => String(x ?? "").replace(/[\u200b\u200c\u200d\u2060\ufeff]/g, "").split(/\s+/).filter(Boolean).join(" ");
  const len = (x) => [...x].length;
  const build = () => {
    const d = Object.fromEntries(new FormData(f)), now = nowSec();
    const goal = parseGen(d.goal), cap = parseGen(d.cap), minp = parseGen(d.minp), days = Number(normNum(d.days));
    const raw = [d.title, d.pitch, d.m1, d.m2, d.m3].map((x) => String(x ?? ""));
    const title = norm(d.title), pitch = norm(d.pitch);
    const deadline = now + Math.round(days * DAY);
    const ms = [1, 2, 3].map((n, i) => ({ description: norm(d["m" + n]), bps: SPLIT[i], due: deadline + 30 * (i + 1) * DAY }));
    let err = "";
    if (raw.some((x) => HIDDEN.test(x))) err = "Text cannot contain control or text-direction characters (often invisible marks copied from a document). Retype it or paste as plain text.";
    else if (len(title) < 3 || len(title) > 80) err = "Title must be 3-80 characters.";
    else if (len(pitch) < 10 || len(pitch) > 1000) err = "Pitch must be 10-1000 characters.";
    else if (!goal || goal <= 0n) err = "Enter a goal in GEN.";
    else if (!cap || cap < goal) err = "The cap must be at least the goal.";
    else if (!minp || minp < 1n || minp > goal) err = "Minimum pledge must be more than 0 and at most the goal.";
    else if (!(days >= 1 && days <= 89)) err = "Funding window must be 1 to 89 days.";
    else if (ms.some((m) => len(m.description) < 12 || len(m.description) > 500)) err = "Each milestone needs 12-500 characters.";
    const bond = goal ? (goal * 500n + 9999n) / 10000n : 0n;
    return { err, bond, ms, title, args: err ? null : [title, pitch, goal, cap, minp, BigInt(deadline), BigInt(d.strikes), JSON.stringify(ms)] };
  };
  const status = $("#launchmsg");
  const upd = () => {
    const b = build();
    $("#bond").textContent = gen(b.bond, 6);
    $("#json").textContent = JSON.stringify(b.ms, null, 2);
    $("#go").disabled = !chain.ready() || !PP.account;
    $("#go").textContent = !chain.ready() ? "Contract address not set" : !PP.account ? "Connect a wallet first" : "Launch campaign";
  };
  f.oninput = upd; addEventListener("pp-connected", upd); upd();
  $("#go").onclick = async () => {
    const msg = (m, bad, h) => say(status, m, bad, h);
    await clockReady; /* deadlines are computed from the corrected clock */
    const b = build();
    if (b.err) return msg(b.err, true);
    $("#go").disabled = true; msg("Confirm the transaction in your wallet (it locks the bond)…");
    let hash = "";
    try {
      let before = null; try { before = Number(N(await chain.read("campaign_count"))); } catch {}
      const r = await chain.write("launch_campaign", b.args, b.bond, (h) => { hash = h; msg("Submitted. Waiting for validators…", false, h); });
      hash ||= r.hash;
      /* find the new campaign: the newest one by this wallet since the count we saw before sending */
      const n = Number(N(await chain.read("campaign_count"))); let target = null;
      for (let i = n - 1; i >= Math.max(0, before ?? n - 5); i--) {
        const c = await getCampaign(i);
        if (same(c.creator, PP.account)) { if (c.title === b.title) { target = i; break; } if (target === null) target = i; }
      }
      const href = target === null ? "campaigns.html" : "campaign.html?id=" + target;
      msg("Campaign launched.", false, hash);
      const open = document.createElement("a"); open.href = href; open.textContent = " Open it now →"; status.append(open);
      setTimeout(() => (location.href = href), 4000);
    } catch (e) { msg("Launch failed: " + (chain.contractError(e) || e?.shortMessage || e?.message || e), true, hash || e?.hash); upd(); }
  };
}

/* ---------- scroll reveal ---------- */
{
  const els = document.querySelectorAll(".rv");
  if (reduced || !("IntersectionObserver" in window)) els.forEach((e) => e.classList.add("in"));
  else { const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: .15 }); els.forEach((e, i) => { e.style.transitionDelay = (i % 4) * 80 + "ms"; io.observe(e); }); }
  /* animated counters */
  document.querySelectorAll("[data-count]").forEach((el) => { const to = +el.dataset.count; if (reduced) return (el.textContent = to);
    let n = 0; const st = performance.now(); const step = (t) => { n = Math.min(1, (t - st) / 1200); el.textContent = Math.round(to * (1 - Math.pow(1 - n, 3))); if (n < 1) requestAnimationFrame(step); }; requestAnimationFrame(step); });
}
/* ---------- mobile menu ---------- */
{
  const b = $("#menu"), nav = $("header nav");
  if (b) b.onclick = () => { const o = nav.classList.toggle("open"); b.setAttribute("aria-expanded", o); };
}

/* ---------- my pledges ---------- */
const mine = $("#mine");
if (mine) {
  let seq = 0;
  const load = async () => {
    const run = ++seq;
    if (!chain.ready()) return notReady(mine);
    if (!PP.account) { mine.innerHTML = `<p class="note">Connect a wallet to see your activity.</p>`; return; }
    mine.innerHTML = `<p class="note">Loading your campaigns…</p>`;
    try {
      const ids = (await chain.read("list_campaign_ids", [""])).map(Number).sort((a, b) => b - a);
      const rows = (await chain.pool(ids, async (id) => {
        const [c, p] = await Promise.all([getCampaign(id), chain.read("get_position", [BigInt(id), PP.account]).catch(() => ({ pledged: "0", refundable_now: "0" }))]);
        return { c, p };
      })).values;
      if (run !== seq) return;
      const made = rows.filter((r) => same(r.c.creator, PP.account)).map((r) => r.c);
      const backed = rows.filter((r) => N(r.p.pledged) > 0n);
      const owed = backed.reduce((a, r) => a + N(r.p.refundable_now), 0n);
      const total = backed.reduce((a, r) => a + N(r.p.pledged), 0n);
      const bcard = ({ c, p }) => card(c).replace("</a>", `<br><small>Your pledge: <b>${gen(p.pledged)} GEN</b>${N(p.refundable_now) > 0n ? ` · refundable now: <b>${gen(p.refundable_now)} GEN</b>` : ""}</small></a>`);
      mine.innerHTML = `<div class="kv"><div><small>Account</small><b>${short(PP.account)}</b></div><div><small>Campaigns backed</small><b>${backed.length}</b></div><div><small>Total pledged</small><b>${gen(total)} GEN</b></div><div><small>Refundable now</small><b>${gen(owed)} GEN</b></div><div><small>Campaigns launched</small><b>${made.length}</b></div></div>
<h3 style="margin-top:34px">Backed by me</h3><div class="grid">${backed.length ? backed.map(bcard).join("") : `<p class="note">You have not backed any campaign yet. <a href="campaigns.html">Browse campaigns</a>.</p>`}</div>
<h3 style="margin-top:34px">Launched by me</h3><div class="grid">${made.length ? made.map(card).join("") : `<p class="note">You have not launched a campaign. <a href="launch.html">Launch one</a>.</p>`}</div>`;
    } catch (e) { if (run === seq) failRead(mine, e, load); }
  };
  PP.refresh = load; addEventListener("pp-connected", load); load();
}
