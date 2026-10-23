"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const TOUCH = matchMedia("(hover: none)").matches;
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

const CATEGORY_COLOR = {
  Elements: "#ff00ff", Transformations: "#33f5ff", Clones: "#cc66ff", Worlds: "#38b6ff",
  Scale: "#73ee1b", Physics: "#8c11e4", Time: "#ffb547", Style: "#dd005d",
};

// Browser storage keys. Everything here is a per-browser convenience, never required.
const KEY = "vfx4all.key", ACCESS = "vfx4all.access", RESULTS = "vfx4all.results", ACTIVE = "vfx4all.active", SCENE = "vfx4all.scene";
const MAX_RESULTS = 12;

const state = {
  tab: "photo",
  presets: [],
  upcoming: [],
  filter: "All",
  preset: null,
  refs: [],
  ownImage: false,
  photo: { subject: "person", aspect: "16:9", quality: "draft" },
  video: { subject: "person", quality: "draft", audio: "effect" },
  sceneJob: null,
  upload: null,
  cut: 0,
  busy: false,
  job: null,
};

/* ---------- helpers ---------- */

function stored(name) {
  try { return localStorage.getItem(name) || ""; } catch { return ""; }
}

function store(name, value) {
  try {
    if (value) localStorage.setItem(name, value); else localStorage.removeItem(name);
    return true;
  } catch { return false; }
}

function storedJSON(name, fallback) {
  try { return JSON.parse(stored(name)) ?? fallback; } catch { return fallback; }
}

const userKey = () => stored(KEY);
const accessCode = () => stored(ACCESS);

function headers(json = true) {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  const key = userKey();
  if (key) h["X-Comfy-Key"] = key;
  const code = accessCode();
  if (code) h["X-Access-Code"] = code;
  return h;
}

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

class Cancelled extends Error {}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    const message = typeof d === "string" ? d : Array.isArray(d) && d[0]?.msg ? d[0].msg : `HTTP ${res.status}`;
    if (res.status === 403) openSettings(message);
    throw new ApiError(message, res.status);
  }
  return data;
}

let toastTimer;
function toast(message, bad = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("bad", bad);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), bad ? 6000 : 2600);
}

// A 403 already opened Settings with the server's message, so it needs no toast.
function fail(err) {
  if (err instanceof Cancelled) return toast("Cancelled. Nothing else runs for this job.");
  if (err?.status !== 403) toast(err.message, true);
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of [].concat(children)) if (child) node.append(child);
  return node;
}

function icon(name, cls = "ic") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

function flash(node) {
  node.classList.add("flash");
  setTimeout(() => node.classList.remove("flash"), 1600);
}

function setBusy(busy) {
  state.busy = busy;
  $$("#makeBtn, #sceneBtn, #animateBtn, #rebuildBtn, #spliceBtn, .rerun").forEach((b) => (b.disabled = busy));
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const qualityLabel = (q) => (q === "hq" ? "HQ" : "Draft");
const presetName = (id = state.preset) => state.presets.find((p) => p.id === id)?.name || id;

/* ---------- hero hex grid (reacts to the cursor, fires random bursts) ---------- */

function hexGrid(canvas) {
  const ctx = canvas.getContext("2d");
  const size = 44;
  let cells = [], w = 0, h = 0, raf = 0, last = performance.now(), visible = true;

  function layout() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cells = [];
    const hw = Math.sqrt(3) * size, vh = 1.5 * size;
    for (let r = -1; r * vh < h + size; r++) {
      for (let c = -1; c * hw < w + hw; c++) cells.push({ x: c * hw + (r % 2 ? hw / 2 : 0), y: r * vh, b: 0, d: 600 });
    }
  }
  function path(x, y, s) {
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = (Math.PI / 180) * (60 * i - 30);
      const px = x + s * Math.cos(a), py = y + s * Math.sin(a);
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    }
    ctx.closePath();
  }
  function fire(cx, cy, radius, chance) {
    for (const c of cells) {
      if (Math.hypot(c.x - cx, c.y - cy) < radius && Math.random() < chance) {
        c.b = 0.05 + Math.random() * 0.15;
        c.d = 350 + Math.random() * 900;
      }
    }
  }
  function frame(now) {
    const dt = Math.min(now - last, 64);
    last = now;
    ctx.clearRect(0, 0, w, h);
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(247, 0, 253, 0.09)";
    for (const c of cells) {
      path(c.x, c.y, size - 1.5);
      ctx.stroke();
      if (c.b > 0.004) {
        ctx.fillStyle = `rgba(247, 0, 253, ${c.b.toFixed(3)})`;
        ctx.fill();
        c.b *= Math.pow(0.5, dt / (c.d / 2));
      }
    }
    raf = visible ? requestAnimationFrame(frame) : 0;
  }
  layout();
  addEventListener("resize", layout);
  const host = canvas.parentElement;
  host.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect();
    fire(e.clientX - r.left, e.clientY - r.top, size * 2.2, 0.3);
  });
  if (!REDUCED) {
    const burst = () => {
      if (visible) fire(Math.random() * w, Math.random() * h, size * 2.6, 0.4);
      setTimeout(burst, 800 + Math.random() * 1600);
    };
    burst();
    new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible && !raf) { last = performance.now(); raf = requestAnimationFrame(frame); }
    }).observe(host);
    raf = requestAnimationFrame(frame);
  } else {
    frame(performance.now());
  }
}

/* ---------- effects rail ---------- */

function presetAllowed(p) {
  if (state.tab === "video") return p.modes.includes("video");
  if (state.ownImage) return p.modes.includes("own_image");
  return p.modes.includes("scene");
}

function whyNot(p) {
  if (state.tab === "video") return `${p.name} only runs from a photo. Pick another effect for video.`;
  if (state.ownImage) return `${p.name} needs its own scene. Turn off "Animate my image as it is" to use it.`;
  return `${p.name} does not run from a photo scene.`;
}

// After a change of mode, drop a selected effect the new mode cannot run.
function dropDisallowed() {
  const current = state.presets.find((p) => p.id === state.preset);
  if (current && !presetAllowed(current)) {
    toast(whyNot(current));
    selectPreset(null);
  }
}

function allItems() {
  const live = state.presets.map((p) => ({ ...p, live: true }));
  const soon = state.upcoming.map((u, i) => ({ ...u, id: `soon-${i}`, live: false }));
  return [...live, ...soon];
}

function renderChips() {
  const items = allItems();
  const cats = ["All", ...Object.keys(CATEGORY_COLOR).filter((c) => items.some((i) => i.category === c))];
  const chips = $("#chips");
  chips.replaceChildren(...cats.map((cat) => {
    const n = cat === "All" ? items.length : items.filter((i) => i.category === cat).length;
    return el("button", {
      class: `chip${state.filter === cat ? " on" : ""}`, "aria-pressed": String(state.filter === cat),
      style: `--c:${CATEGORY_COLOR[cat] || "#ff00ff"}`,
      onclick: () => { state.filter = cat; renderChips(); renderRail(); $("#rail").scrollTo({ left: 0, behavior: "smooth" }); },
    }, el("span", {}, [document.createTextNode(cat), el("span", { class: "n", text: String(n) })]));
  }));
}

let cardObserver;
function renderRail() {
  const rail = $("#rail");
  const items = allItems().filter((i) => state.filter === "All" || i.category === state.filter);
  cardObserver?.disconnect();
  rail.replaceChildren(...items.map(card));
  if (TOUCH) {
    cardObserver = new IntersectionObserver((entries) => {
      for (const { target, isIntersecting } of entries) {
        const v = target.querySelector("video");
        if (!v) continue;
        if (isIntersecting) { v.play().then(() => target.classList.add("playing")).catch(() => {}); }
        else { v.pause(); target.classList.remove("playing"); }
      }
    }, { root: rail, threshold: 0.7 });
    $$(".card", rail).forEach((c) => cardObserver.observe(c));
  }
  updateRailBar();
}

function card(item) {
  const color = CATEGORY_COLOR[item.category] || "#ff00ff";
  if (!item.live) {
    return el("div", { class: "card soon", role: "option", "aria-disabled": "true", style: `--c:${color}`, title: `${item.name}, coming soon` }, [
      el("div", { class: "card-in" }, [
        el("div", { class: "art" }, icon(item.icon || "sparkles", "ic big")),
        el("div", { class: "card-shade" }),
        el("div", { class: "card-top" }, [el("span", { class: "tag", text: item.category }), el("span", { class: "tag soon" }, [icon("lock", "ic sm"), document.createTextNode("Soon")])]),
        el("div", { class: "card-body" }, [
          el("span", { class: "card-name" }, [icon(item.icon || "sparkles"), document.createTextNode(item.name)]),
          el("span", { class: "card-desc", text: item.description }),
        ]),
      ]),
    ]);
  }
  const allowed = presetAllowed(item);
  const video = el("video", { muted: true, loop: true, playsinline: true, preload: "none", src: item.preview });
  video.muted = true;
  const node = el("button", {
    class: `card${state.preset === item.id ? " selected" : ""}${allowed ? "" : " disabled"}`,
    role: "option", "aria-selected": String(state.preset === item.id), "aria-disabled": String(!allowed),
    "data-id": item.id, style: `--c:${color}`,
    onclick: (e) => {
      if (dragMoved) return e.preventDefault();
      if (!allowed) return toast(whyNot(item));
      const again = state.preset === item.id;
      selectPreset(item.id);
      if (again || e.target.closest(".card-use")) $("#studio").scrollIntoView({ behavior: "smooth" });
    },
    onmouseenter: () => { if (!TOUCH) video.play().then(() => node.classList.add("playing")).catch(() => {}); },
    onmouseleave: () => { if (!TOUCH) { video.pause(); node.classList.remove("playing"); } },
  }, el("span", { class: "card-in" }, [
    el("img", { src: item.thumb, alt: "", loading: "lazy" }), video,
    el("span", { class: "card-shade" }),
    el("span", { class: "card-top" }, [
      el("span", { class: "tag", text: item.category }),
      el("span", {}, [
        item.experimental ? el("span", { class: "tag beta", text: "Beta" }) : el("span", { class: "tag live" }, [icon("play", "ic sm"), document.createTextNode("Live")]),
      ]),
    ]),
    el("span", { class: "card-body" }, [
      el("span", { class: "card-name" }, [icon(item.icon || "sparkles"), document.createTextNode(item.name)]),
      el("span", { class: "card-desc", text: item.description }),
      el("span", { class: "card-use" }, [icon(state.preset === item.id ? "check" : "wand", "ic sm"),
        document.createTextNode(state.preset === item.id ? "Selected, go to studio" : "Use this effect")]),
    ]),
  ]));
  return node;
}

function selectPreset(id) {
  state.preset = id;
  const p = state.presets.find((x) => x.id === id);
  $$(".card[data-id]").forEach((c) => {
    const on = c.dataset.id === id;
    c.classList.toggle("selected", on);
    c.setAttribute("aria-selected", String(on));
    const use = c.querySelector(".card-use");
    if (use) use.replaceChildren(icon(on ? "check" : "wand", "ic sm"), document.createTextNode(on ? "Selected, go to studio" : "Use this effect"));
  });
  $("#chosenName").textContent = p ? p.name : "Pick one above";
  const thumb = $("#chosenThumb");
  if (p) thumb.src = p.thumb; else thumb.removeAttribute("src");
  const link = $("#comfyLink");
  link.classList.toggle("hidden", !p?.comfy_app);
  if (p?.comfy_app) link.href = p.comfy_app;
}

function updateRailBar() {
  const rail = $("#rail");
  const total = rail.scrollWidth || 1;
  $("#railBar").style.width = `${Math.max(6, (rail.clientWidth / total) * 100)}%`;
  $("#railBar").style.marginLeft = `${(rail.scrollLeft / total) * 100}%`;
}

let dragMoved = false;
function bindRail() {
  const rail = $("#rail");
  const step = () => (rail.querySelector(".card")?.getBoundingClientRect().width || 320) + 18;
  $("#railPrev").addEventListener("click", () => rail.scrollBy({ left: -step() * 2, behavior: "smooth" }));
  $("#railNext").addEventListener("click", () => rail.scrollBy({ left: step() * 2, behavior: "smooth" }));
  rail.addEventListener("scroll", updateRailBar, { passive: true });
  addEventListener("resize", updateRailBar);
  rail.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") rail.scrollBy({ left: step(), behavior: "smooth" });
    if (e.key === "ArrowLeft") rail.scrollBy({ left: -step(), behavior: "smooth" });
  });
  let startX = 0, startLeft = 0, down = false;
  rail.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "mouse") return;
    down = true; dragMoved = false; startX = e.clientX; startLeft = rail.scrollLeft;
  });
  addEventListener("pointermove", (e) => {
    if (!down) return;
    const dx = e.clientX - startX;
    if (Math.abs(dx) > 5) { dragMoved = true; rail.classList.add("dragging"); }
    if (dragMoved) rail.scrollLeft = startLeft - dx;
  });
  addEventListener("pointerup", () => {
    if (!down) return;
    down = false;
    rail.classList.remove("dragging");
    setTimeout(() => (dragMoved = false), 0);
  });
}

/* ---------- jobs ---------- */

function clock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function offScreen(node) {
  const r = node.getBoundingClientRect();
  return r.top < 70 || r.bottom > innerHeight;
}

// Follow a job until it ends. `meta` ({title, kind}) is kept in the browser so a reload can pick it up.
async function waitJob(job, meta = {}) {
  const box = $("#progress");
  box.classList.remove("hidden");
  $("#cancelBtn").disabled = false;
  state.job = job;
  store(ACTIVE, JSON.stringify({ id: job.id, title: meta.title || "", kind: meta.kind || job.kind }));
  if (offScreen(box)) box.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "center" });
  const started = job.created ? job.created * 1000 : Date.now();
  const tick = () => ($("#progressTime").textContent = clock((Date.now() - started) / 1000));
  tick();
  const timer = setInterval(tick, 1000);
  try {
    for (;;) {
      const pct = Math.round((job.progress || 0) * 100);
      $("#progressBar").style.width = `${pct}%`;
      $("#progressPct").textContent = `${pct}%`;
      $("#progressText").textContent = job.message || job.status;
      if (job.status === "succeeded") return job;
      if (job.status === "failed") throw new Error(job.error || "The job failed");
      if (job.status === "cancelled") throw new Cancelled();
      await sleep(1500);
      job = await api(`/api/jobs/${job.id}`);
      state.job = job;
    }
  } finally {
    clearInterval(timer);
    box.classList.add("hidden");
    state.job = null;
    store(ACTIVE, "");
  }
}

async function cancelJob() {
  if (!state.job) return;
  $("#cancelBtn").disabled = true;
  $("#progressText").textContent = "Cancelling";
  try { await api(`/api/jobs/${state.job.id}/cancel`, { method: "POST", headers: headers() }); }
  catch (err) { $("#cancelBtn").disabled = false; fail(err); }
}

function startJob(kind, body) {
  return api(`/api/jobs/${kind}`, { method: "POST", headers: headers(), body: JSON.stringify(body) });
}

async function runJob(kind, body, title) {
  const done = await waitJob(await startJob(kind, body), { title, kind });
  addResult(title, done);
  return done;
}

function promptBox(text) {
  return el("details", { class: "prompt" }, [el("summary", { text: "Prompt" }), el("p", { text })]);
}

// The request fields a result can be run again with, by job kind.
const RERUN_FIELDS = {
  effect: ["preset", "scene_job", "image", "subject", "aspect", "quality"],
  splice: ["preset", "video", "seconds", "subject", "quality", "audio"],
};

function resultTitle(kind, body) {
  const where = kind === "splice" ? ` from ${Number(body.seconds || 0).toFixed(2)} s` : "";
  return `${presetName(body.preset)}${where} | ${qualityLabel(body.quality)}`;
}

function rerun(job, overrides = {}) {
  const body = {};
  for (const k of RERUN_FIELDS[job.kind] || []) {
    const v = job.params?.[k];
    if (v !== null && v !== undefined && v !== "") body[k] = v;
  }
  Object.assign(body, overrides);
  return runJob(job.kind, body, resultTitle(job.kind, body));
}

function addResult(title, job, fresh = true) {
  $("#emptyState")?.remove();
  const p = job.params || {};
  const seed = p.seed_used;
  const links = [el("a", { href: job.outputs.video, download: "" }, [icon("download", "ic sm"), document.createTextNode("Download")])];
  if (job.outputs.effect) links.push(el("a", { href: job.outputs.effect, download: "" }, [icon("film", "ic sm"), document.createTextNode("Effect only")]));
  const video = el("video", { src: job.outputs.video, controls: true, playsinline: true, preload: fresh ? "auto" : "metadata", poster: job.outputs.poster || null });
  const media = el("div", { class: "result-media" }, video);
  const actions = [];
  if (RERUN_FIELDS[job.kind]) {
    actions.push(el("button", { type: "button", class: "rerun", onclick: () => run(() => rerun(job)) },
      [icon("sparkles", "ic sm"), document.createTextNode("New take")]));
    if (p.quality !== "hq" && seed !== null && seed !== undefined) {
      actions.push(el("button", { type: "button", class: "rerun", onclick: () => run(() => rerun(job, { quality: "hq", seed })) },
        [icon("gem", "ic sm"), document.createTextNode("HQ of this take")]));
    }
  }
  if (job.kind === "splice" && p.video) {
    const btn = el("button", { type: "button", "aria-pressed": "false", onclick: () => toggleCompare(node, job, btn) },
      [icon("compare", "ic sm"), document.createTextNode("Compare")]);
    actions.push(btn);
  }
  if (seed !== null && seed !== undefined) actions.push(el("span", { class: "seed", text: `Seed ${seed}` }));
  const node = el("article", { class: "result", "data-id": job.id }, [
    media,
    el("div", { class: "meta" }, [el("span", { text: title }), el("span", {}, links)]),
    actions.length ? el("div", { class: "result-actions" }, actions) : null,
    p.prompt ? promptBox(p.prompt) : null,
  ]);
  $("#results").prepend(node);
  if (state.busy) $$(".rerun", node).forEach((b) => (b.disabled = true));
  if (fresh) {
    rememberResult(job.id, title);
    video.play().catch(() => {});
    node.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "nearest" });
  }
}

// Before and after for a splice: your clip over the result, wiped with a slider, playing in step.
function toggleCompare(node, job, btn) {
  const media = $(".result-media", node);
  const main = $("video", media);
  let orig = $(".compare-orig", media);
  if (!orig) {
    orig = el("video", { class: "compare-orig", src: `/files/uploads/${job.params.video}`, playsinline: true, preload: "auto" });
    orig.muted = true;
    const line = el("span", { class: "compare-line" });
    const range = el("input", { type: "range", min: "0", max: "100", value: "50", "aria-label": "Wipe between the result and your clip" });
    const wipe = () => {
      orig.style.clipPath = `inset(0 0 46px ${range.value}%)`;
      line.style.left = `${range.value}%`;
    };
    const on = () => !orig.classList.contains("hidden");
    const sync = () => { if (on() && Math.abs(orig.currentTime - main.currentTime) > 0.12) orig.currentTime = main.currentTime; };
    main.addEventListener("play", () => { if (on()) { sync(); orig.play().catch(() => {}); } });
    main.addEventListener("pause", () => orig.pause());
    main.addEventListener("seeked", sync);
    main.addEventListener("timeupdate", sync);
    main.addEventListener("ratechange", () => (orig.playbackRate = main.playbackRate));
    range.addEventListener("input", wipe);
    media.append(orig, line, el("span", { class: "compare-tag l", text: "Result" }), el("span", { class: "compare-tag r", text: "Your clip" }));
    media.after(el("label", { class: "compare-row" }, [el("span", { text: "Result" }), range, el("span", { text: "Your clip" })]));
    wipe();
  } else {
    const show = orig.classList.contains("hidden");
    $$(".compare-orig, .compare-line, .compare-tag", media).forEach((n) => n.classList.toggle("hidden", !show));
    $(".compare-row", node).classList.toggle("hidden", !show);
    if (!show) orig.pause();
  }
  const shown = !orig.classList.contains("hidden");
  btn.setAttribute("aria-pressed", String(shown));
  if (shown) {
    orig.currentTime = main.currentTime;
    if (!main.paused) orig.play().catch(() => {});
  }
}

function rememberResult(id, title) {
  const list = storedJSON(RESULTS, []).filter((r) => r.id !== id);
  list.unshift({ id, title });
  store(RESULTS, JSON.stringify(list.slice(0, MAX_RESULTS)));
}

// Bring back what this browser made before a reload: results, the last scene and a job still running.
async function restore() {
  const kept = [];
  for (const r of [...storedJSON(RESULTS, [])].reverse()) {
    try {
      const job = await api(`/api/jobs/${r.id}`);
      if (job.status === "succeeded" && job.outputs?.video) { addResult(r.title, job, false); kept.unshift(r); }
    } catch { /* gone from the server */ }
  }
  store(RESULTS, kept.length ? JSON.stringify(kept) : "");

  const sceneId = stored(SCENE);
  if (sceneId) {
    try {
      const job = await api(`/api/jobs/${sceneId}`);
      if (job.status === "succeeded" && job.outputs?.scene) showScene(job); else store(SCENE, "");
    } catch { store(SCENE, ""); }
  }

  const active = storedJSON(ACTIVE, null);
  if (!active?.id) return;
  let job;
  try { job = await api(`/api/jobs/${active.id}`); } catch { store(ACTIVE, ""); return; }
  const finish = (done) => {
    if ((active.kind || done.kind) === "scene") showScene(done);
    else addResult(active.title || presetName(done.params?.preset), done);
  };
  if (job.status === "queued" || job.status === "running") run(async () => finish(await waitJob(job, active)));
  else {
    store(ACTIVE, "");
    if (job.status === "succeeded") finish(job);
  }
}

/* ---------- photo mode ---------- */

function needConsent() {
  if ($("#consent").checked) return true;
  toast("Confirm first that everyone in it agreed to be used", true);
  flash($("#consentRow"));
  $("#consent").focus();
  return false;
}

async function uploadFiles(files) {
  const out = [];
  for (const file of files) {
    const form = new FormData();
    form.append("file", file);
    form.append("consent", "true");
    out.push(await api("/api/upload", { method: "POST", body: form, headers: headers(false) }));
  }
  return out;
}

function renderThumbs() {
  $("#photoThumbs").replaceChildren(...state.refs.map((ref, i) => el("div", { class: "thumb" }, [
    el("img", { src: ref.url, alt: ref.name || "Reference photo" }),
    el("button", { "aria-label": "Remove photo", text: "x", onclick: (e) => { e.preventDefault(); state.refs.splice(i, 1); renderThumbs(); } }),
  ])));
}

const isHeic = (f) => /\.(heic|heif)$/i.test(f.name) || /image\/hei[cf]/i.test(f.type);

async function addPhotos(fileList) {
  const all = [...fileList];
  if (all.some(isHeic)) return toast("HEIC photos from an iPhone are not supported yet. Export them as JPG first.", true);
  if (state.refs.length >= 2) return toast("Two photos at most. Remove one first.", true);
  const images = all.filter((f) => f.type.startsWith("image/"));
  if (!images.length) return toast("Use PNG, JPG or WEBP photos", true);
  const big = images.find((f) => f.size > imageLimits.max_mb * 1024 * 1024);
  if (big) return toast(`${big.name} is over ${imageLimits.max_mb} MB. Use a smaller photo.`, true);
  try { state.refs.push(...(await uploadFiles(images.slice(0, 2 - state.refs.length)))); renderThumbs(); } catch (err) { fail(err); }
}

function needPhoto() {
  if (!state.preset) { toast("Pick an effect first", true); $("#effects").scrollIntoView({ behavior: "smooth" }); return false; }
  if (!state.refs.length) { toast("Add a photo first", true); return false; }
  return true;
}

function showScene(job) {
  state.sceneJob = job.id;
  store(SCENE, job.id);
  $("#sceneImg").src = `${job.outputs.scene}?t=${Date.now()}`;
  const details = $("#scenePrompt");
  $("p", details).textContent = job.params?.prompt || "";
  details.classList.toggle("hidden", !job.params?.prompt);
  $("#sceneCard").classList.toggle("hidden", state.tab !== "photo");
}

async function buildScene() {
  const done = await waitJob(await startJob("scene", {
    preset: state.preset, refs: state.refs.map((r) => r.id), subject: state.photo.subject,
    notes: $("#notes").value, aspect: state.photo.aspect,
  }), { title: presetName(), kind: "scene" });
  showScene(done);
  return done;
}

function animate() {
  const body = { preset: state.preset, subject: state.photo.subject, aspect: state.photo.aspect, quality: state.photo.quality };
  if (state.ownImage) body.image = state.refs[0].id; else body.scene_job = state.sceneJob;
  return runJob("effect", body, resultTitle("effect", body));
}

async function run(task) {
  if (state.busy) return;
  setBusy(true);
  try { await task(); } catch (err) { fail(err); } finally { setBusy(false); }
}

/* ---------- video mode ---------- */

function drawCut() {
  const v = $("#srcVideo"), c = $("#cutCanvas");
  if (!v.videoWidth) return;
  c.width = 160;
  c.height = Math.round((160 * v.videoHeight) / v.videoWidth);
  c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
}

// Same numbers as the server, which has the last word; /api/health refreshes them.
let videoLimits = { min_seconds: 2, max_seconds: 60, min_short_side: 480, max_long_side: 4096, max_mb: 500 };
let imageLimits = { max_mb: 20, max_side: 8192 };

const sideLabel = (px) => (px >= 3840 ? "4K" : `${px}p`);

function paintLimits() {
  const v = videoLimits;
  $("#limSeconds").textContent = `${v.min_seconds} to ${v.max_seconds} s`;
  $("#limRes").textContent = `${v.min_short_side}p to ${sideLabel(v.max_long_side)}`;
  $("#limMb").textContent = `up to ${v.max_mb} MB`;
  $("#photoLimit").textContent = `PNG, JPG or WEBP, up to ${imageLimits.max_mb} MB each.`;
}

function localVideoMeta(file) {
  return new Promise((resolve) => {
    const v = document.createElement("video");
    const url = URL.createObjectURL(file);
    const done = (meta) => { URL.revokeObjectURL(url); resolve(meta); };
    v.preload = "metadata";
    v.onloadedmetadata = () => done({ seconds: v.duration, width: v.videoWidth, height: v.videoHeight });
    v.onerror = () => done(null); // a codec the browser cannot read: let the server decide
    v.src = url;
  });
}

function videoProblem(file, meta) {
  const lim = videoLimits;
  if (file.size > lim.max_mb * 1024 * 1024) return `That clip is over ${lim.max_mb} MB. Trim or compress it first.`;
  if (!meta || !meta.width) return null;
  if (meta.seconds < lim.min_seconds) return `That clip is ${meta.seconds.toFixed(1)} s. Use one of at least ${lim.min_seconds} s.`;
  if (meta.seconds > lim.max_seconds) return `That clip is ${Math.round(meta.seconds)} s. Trim it to ${lim.max_seconds} s or less around the moment you want.`;
  if (Math.min(meta.width, meta.height) < lim.min_short_side) return `That clip is ${meta.width}x${meta.height}. Use ${lim.min_short_side}p or more.`;
  if (Math.max(meta.width, meta.height) > lim.max_long_side) return `That clip is ${meta.width}x${meta.height}. Use ${sideLabel(lim.max_long_side)} or less.`;
  return null;
}

async function addVideo(fileList) {
  const file = [...fileList].find((f) => f.type.startsWith("video/"));
  if (!file) return toast("Drop an MP4, MOV, WEBM or MKV clip", true);
  const problem = videoProblem(file, await localVideoMeta(file));
  if (problem) {
    flash($("#videoLimits"));
    return toast(problem, true);
  }
  try {
    const [meta] = await uploadFiles([file]);
    state.upload = meta; state.cut = 0;
    const v = $("#srcVideo");
    v.src = meta.url;
    $("#videoBox").classList.remove("hidden");
    $("#cutLabel").textContent = "0.00 s";
    v.addEventListener("loadeddata", drawCut, { once: true });
  } catch (err) { fail(err); }
}

function splice() {
  if (!state.preset) return toast("Pick an effect first", true);
  if (!state.upload) return toast("Add a clip first", true);
  const body = {
    preset: state.preset, video: state.upload.id, seconds: state.cut,
    subject: state.video.subject, quality: state.video.quality, audio: state.video.audio,
  };
  return runJob("splice", body, resultTitle("splice", body));
}

/* ---------- settings ---------- */

function openSettings(message = "") {
  const dialog = $("#settings");
  $("#keyInput").value = userKey();
  $("#accessInput").value = accessCode();
  const msg = $("#settingsMsg");
  msg.textContent = message;
  msg.classList.toggle("hidden", !message);
  if (message) $("#accessField").classList.remove("hidden");
  dialog.returnValue = "";
  if (!dialog.open) dialog.showModal();
}

/* ---------- wiring ---------- */

function bindDrop(zone, input, handler) {
  zone.addEventListener("click", (e) => { if (e.target !== input && !needConsent()) e.preventDefault(); });
  zone.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    if (needConsent()) input.click();
  });
  input.addEventListener("change", () => { if (needConsent()) handler(input.files); input.value = ""; });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("over");
    if (needConsent()) handler(e.dataTransfer.files);
  });
}

function bindSegments() {
  for (const seg of $$(".seg")) {
    const scope = seg.closest("#videoPanel") ? state.video : state.photo;
    const buttons = $$("button", seg);
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.classList.contains("on"))));
    seg.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      e.preventDefault();
      buttons.forEach((b) => { const on = b === btn; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
      scope[seg.dataset.name] = btn.dataset.value;
    });
  }
}

function switchTab(tab) {
  state.tab = tab;
  $$(".mode").forEach((m) => { const on = m.dataset.tab === tab; m.classList.toggle("active", on); m.setAttribute("aria-selected", String(on)); });
  $("#photoPanel").classList.toggle("hidden", tab !== "photo");
  $("#videoPanel").classList.toggle("hidden", tab !== "video");
  $("#sceneCard").classList.toggle("hidden", tab !== "photo" || !state.sceneJob);
  dropDisallowed();
  renderRail();
}

async function refreshKeyStatus() {
  const pill = $("#keyStatus");
  let text;
  try {
    const health = await api("/api/health");
    if (health.video_limits) videoLimits = health.video_limits;
    if (health.image_limits) imageLimits = health.image_limits;
    paintLimits();
    $("#accessField").classList.toggle("hidden", !health.access_required && !accessCode());
    const own = Boolean(userKey());
    const needsCode = health.access_required && !accessCode();
    pill.className = `status ${!needsCode && (own || health.has_key) ? "ok" : "warn"}`;
    text = needsCode ? "Access code needed" : own ? "Your Comfy key" : health.has_key ? "Comfy Cloud ready" : "No Comfy key";
  } catch {
    pill.className = "status warn";
    text = "Server offline";
  }
  $(".txt", pill).textContent = text;
  pill.setAttribute("aria-label", text);
  pill.title = text;
}

function bindReveal() {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  }, { threshold: 0.12 });
  $$(".reveal").forEach((n, i) => { n.style.transitionDelay = `${Math.min(i % 4, 3) * 70}ms`; io.observe(n); });
}

async function init() {
  hexGrid($("#hexCanvas"));
  bindReveal();
  bindSegments();
  bindRail();
  bindDrop($("#photoDrop"), $("#photoInput"), addPhotos);
  bindDrop($("#videoDrop"), $("#videoInput"), addVideo);
  $$(".mode").forEach((m) => m.addEventListener("click", () => switchTab(m.dataset.tab)));

  $("#ownImage").addEventListener("change", (e) => {
    state.ownImage = e.target.checked;
    $("#notesField").classList.toggle("hidden", state.ownImage);
    $("#sceneBtn").classList.toggle("hidden", state.ownImage);
    dropDisallowed();
    renderRail();
  });
  $("#makeBtn").addEventListener("click", () => run(async () => { if (!needPhoto()) return; if (!state.ownImage) await buildScene(); await animate(); }));
  $("#sceneBtn").addEventListener("click", () => run(async () => { if (needPhoto()) await buildScene(); }));
  $("#rebuildBtn").addEventListener("click", () => run(async () => { if (needPhoto()) await buildScene(); }));
  $("#animateBtn").addEventListener("click", () => run(async () => {
    if (!state.preset) return toast("Pick an effect first", true);
    if (!state.sceneJob) return toast("Build a scene first", true);
    await animate();
  }));
  $("#setCutBtn").addEventListener("click", () => {
    state.cut = $("#srcVideo").currentTime || 0;
    $("#cutLabel").textContent = `${state.cut.toFixed(2)} s`;
    drawCut();
  });
  $("#spliceBtn").addEventListener("click", () => run(splice));
  $("#cancelBtn").addEventListener("click", cancelJob);

  const dialog = $("#settings");
  $("#settingsBtn").addEventListener("click", () => openSettings());
  dialog.addEventListener("close", () => {
    let ok = true;
    if (dialog.returnValue === "save") ok = store(KEY, $("#keyInput").value.trim()) && store(ACCESS, $("#accessInput").value.trim());
    if (dialog.returnValue === "clear") ok = store(KEY, "") && store(ACCESS, "");
    if (!ok) toast("This browser blocks local storage, so the key and the code cannot be saved", true);
    refreshKeyStatus();
  });

  paintLimits();
  try {
    const [presets, upcoming] = await Promise.all([api("/api/presets"), fetch("/static/upcoming.json").then((r) => r.json()).catch(() => [])]);
    state.presets = presets;
    state.upcoming = upcoming;
    const total = presets.length + upcoming.length;
    $("#liveCount").textContent = upcoming.length ? `${presets.length} effects, ${upcoming.length} coming` : `${presets.length} effects`;
    $("#heroCount").textContent = `Browse ${total} effects`;
    $("#effectsSub").textContent = `Swipe through the catalog. ${TOUCH ? "Each card plays as it comes into view." : "Hover a card to see it move."}${upcoming.length ? " Locked cards are on their way." : ""}`;
    $("#comfyHint").classList.toggle("hidden", !presets.some((p) => p.comfy_app));
    renderChips();
    renderRail();
    if (presets[0]) selectPreset(presets[0].id);
  } catch (err) { toast(`Could not load effects: ${err.message}`, true); }
  await refreshKeyStatus();
  restore();
}

init();
