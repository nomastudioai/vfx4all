"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const TOUCH = matchMedia("(hover: none)").matches;
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

const CATEGORY_COLOR = {
  Elements: "#ff00ff", Transformations: "#33f5ff", Clones: "#cc66ff", Worlds: "#38b6ff",
  Scale: "#73ee1b", Physics: "#8c11e4", Time: "#ffb547", Style: "#dd005d",
};

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
};

/* ---------- helpers ---------- */

function userKey() {
  try { return localStorage.getItem("vfx4all.key") || ""; } catch { return ""; }
}

function headers(json = true) {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  const key = userKey();
  if (key) h["X-Comfy-Key"] = key;
  return h;
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || `HTTP ${res.status}`);
    throw new Error(detail);
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

function setBusy(busy) {
  state.busy = busy;
  $$("#makeBtn, #sceneBtn, #animateBtn, #rebuildBtn, #spliceBtn").forEach((b) => (b.disabled = busy));
}

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
      class: `chip${state.filter === cat ? " on" : ""}`, role: "tab", "aria-selected": String(state.filter === cat),
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
          el("h3", { class: "card-name" }, [icon(item.icon || "sparkles"), document.createTextNode(item.name)]),
          el("p", { class: "card-desc", text: item.description }),
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
      if (!allowed) return toast(`${item.name} needs its own scene, so it only runs from a photo`);
      const again = state.preset === item.id;
      selectPreset(item.id);
      if (again || e.target.closest(".card-use")) $("#studio").scrollIntoView({ behavior: "smooth" });
    },
    onmouseenter: () => { if (!TOUCH) video.play().then(() => node.classList.add("playing")).catch(() => {}); },
    onmouseleave: () => { if (!TOUCH) { video.pause(); node.classList.remove("playing"); } },
  }, el("div", { class: "card-in" }, [
    el("img", { src: item.thumb, alt: "", loading: "lazy" }), video,
    el("div", { class: "card-shade" }),
    el("div", { class: "card-top" }, [
      el("span", { class: "tag", text: item.category }),
      el("span", {}, [
        item.experimental ? el("span", { class: "tag beta", text: "Beta" }) : el("span", { class: "tag live" }, [icon("play", "ic sm"), document.createTextNode("Live")]),
      ]),
    ]),
    el("div", { class: "card-body" }, [
      el("h3", { class: "card-name" }, [icon(item.icon || "sparkles"), document.createTextNode(item.name)]),
      el("p", { class: "card-desc", text: item.description }),
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
  $("#chosenThumb").src = p ? p.thumb : "";
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

async function waitJob(job) {
  const box = $("#progress");
  box.classList.remove("hidden");
  for (;;) {
    const pct = Math.round((job.progress || 0) * 100);
    $("#progressBar").style.width = `${pct}%`;
    $("#progressPct").textContent = `${pct}%`;
    $("#progressText").textContent = job.message || job.status;
    if (job.status === "succeeded") break;
    if (job.status === "failed") { box.classList.add("hidden"); throw new Error(job.error || "The job failed"); }
    await new Promise((r) => setTimeout(r, 1500));
    job = await api(`/api/jobs/${job.id}`);
  }
  box.classList.add("hidden");
  return job;
}

function startJob(kind, body) {
  return api(`/api/jobs/${kind}`, { method: "POST", headers: headers(), body: JSON.stringify(body) });
}

function addResult(title, job, extra = []) {
  $("#emptyState")?.remove();
  const links = [el("a", { href: job.outputs.video, download: "" }, [icon("download", "ic sm"), document.createTextNode("Download")]), ...extra];
  const node = el("article", { class: "result" }, [
    el("video", { src: job.outputs.video, controls: true, playsinline: true, poster: job.outputs.poster || null }),
    el("div", { class: "meta" }, [el("span", { text: title }), el("span", {}, links)]),
  ]);
  $("#results").prepend(node);
  node.querySelector("video").play().catch(() => {});
  node.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

const presetName = () => state.presets.find((p) => p.id === state.preset)?.name || state.preset;

/* ---------- photo mode ---------- */

async function uploadFiles(files) {
  const out = [];
  for (const file of files) {
    const form = new FormData();
    form.append("file", file);
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

async function addPhotos(fileList) {
  const files = [...fileList].filter((f) => f.type.startsWith("image/")).slice(0, 2 - state.refs.length);
  if (!files.length) return toast("Two photos at most, PNG, JPG or WEBP", true);
  try { state.refs.push(...(await uploadFiles(files))); renderThumbs(); } catch (err) { toast(err.message, true); }
}

function needPhoto() {
  if (!state.preset) { toast("Pick an effect first", true); $("#effects").scrollIntoView({ behavior: "smooth" }); return false; }
  if (!state.refs.length) { toast("Add a photo first", true); return false; }
  return true;
}

async function buildScene() {
  const done = await waitJob(await startJob("scene", {
    preset: state.preset, refs: state.refs.map((r) => r.id), subject: state.photo.subject,
    notes: $("#notes").value, aspect: state.photo.aspect,
  }));
  state.sceneJob = done.id;
  $("#sceneImg").src = `${done.outputs.scene}?t=${Date.now()}`;
  $("#sceneCard").classList.remove("hidden");
  return done;
}

async function animate() {
  const body = { preset: state.preset, subject: state.photo.subject, aspect: state.photo.aspect, quality: state.photo.quality };
  if (state.ownImage) body.image = state.refs[0].id; else body.scene_job = state.sceneJob;
  const done = await waitJob(await startJob("effect", body));
  addResult(`${presetName()} | ${state.photo.quality === "hq" ? "HQ" : "Draft"}`, done);
}

async function run(task) {
  if (state.busy) return;
  setBusy(true);
  try { await task(); } catch (err) { toast(err.message, true); } finally { setBusy(false); }
}

/* ---------- video mode ---------- */

function drawCut() {
  const v = $("#srcVideo"), c = $("#cutCanvas");
  if (!v.videoWidth) return;
  c.width = 160;
  c.height = Math.round((160 * v.videoHeight) / v.videoWidth);
  c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
}

// Same numbers as VIDEO_LIMITS on the server, which has the last word; /api/health refreshes them.
let videoLimits = { min_seconds: 2, max_seconds: 60, min_short_side: 480, max_long_side: 4096, max_mb: 500 };

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
  if (Math.min(meta.width, meta.height) < lim.min_short_side) return `That clip is ${meta.width}x${meta.height}. Use 480p or more.`;
  if (Math.max(meta.width, meta.height) > lim.max_long_side) return `That clip is ${meta.width}x${meta.height}. Use 4K or less.`;
  return null;
}

async function addVideo(fileList) {
  const file = [...fileList].find((f) => f.type.startsWith("video/"));
  if (!file) return toast("Drop an MP4, MOV, WEBM or MKV clip", true);
  const problem = videoProblem(file, await localVideoMeta(file));
  if (problem) {
    $("#videoLimits").classList.add("flash");
    setTimeout(() => $("#videoLimits").classList.remove("flash"), 1600);
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
  } catch (err) { toast(err.message, true); }
}

async function splice() {
  if (!state.preset) return toast("Pick an effect first", true);
  if (!state.upload) return toast("Add a clip first", true);
  const done = await waitJob(await startJob("splice", {
    preset: state.preset, video: state.upload.id, seconds: state.cut,
    subject: state.video.subject, quality: state.video.quality, audio: state.video.audio,
  }));
  addResult(`${presetName()} from ${state.cut.toFixed(2)} s`, done, [
    el("a", { href: done.outputs.effect, download: "" }, [icon("film", "ic sm"), document.createTextNode("Effect only")]),
  ]);
}

/* ---------- wiring ---------- */

function bindDrop(zone, input, handler) {
  zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => { handler(input.files); input.value = ""; });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); handler(e.dataTransfer.files); });
}

function bindSegments() {
  for (const seg of $$(".seg")) {
    const scope = seg.closest("#videoPanel") ? state.video : state.photo;
    seg.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      e.preventDefault();
      seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
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
  const current = state.presets.find((p) => p.id === state.preset);
  if (current && !presetAllowed(current)) {
    toast(`${current.name} only runs from a photo. Pick another effect for video.`);
    selectPreset(null);
  }
  renderRail();
}

async function refreshKeyStatus() {
  const pill = $("#keyStatus");
  try {
    const health = await api("/api/health");
    if (health.video_limits) videoLimits = health.video_limits;
    const own = Boolean(userKey());
    pill.className = `status ${own || health.has_key ? "ok" : "warn"}`;
    $(".txt", pill).textContent = own ? "Your Comfy key" : health.has_key ? "Comfy Cloud ready" : "No Comfy key";
  } catch {
    pill.className = "status warn";
    $(".txt", pill).textContent = "Server offline";
  }
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
    renderRail();
  });
  $("#makeBtn").addEventListener("click", () => run(async () => { if (!needPhoto()) return; if (!state.ownImage) await buildScene(); await animate(); }));
  $("#sceneBtn").addEventListener("click", () => run(async () => { if (needPhoto()) await buildScene(); }));
  $("#rebuildBtn").addEventListener("click", () => run(async () => { if (needPhoto()) await buildScene(); }));
  $("#animateBtn").addEventListener("click", () => run(async () => { if (!state.sceneJob) return toast("Build a scene first", true); await animate(); }));
  $("#setCutBtn").addEventListener("click", () => {
    state.cut = $("#srcVideo").currentTime || 0;
    $("#cutLabel").textContent = `${state.cut.toFixed(2)} s`;
    drawCut();
  });
  $("#spliceBtn").addEventListener("click", () => run(splice));

  const dialog = $("#settings");
  $("#settingsBtn").addEventListener("click", () => { $("#keyInput").value = userKey(); dialog.showModal(); });
  dialog.addEventListener("close", () => {
    try {
      if (dialog.returnValue === "save") localStorage.setItem("vfx4all.key", $("#keyInput").value.trim());
      if (dialog.returnValue === "clear") localStorage.removeItem("vfx4all.key");
    } catch { toast("This browser blocks local storage, so the key cannot be saved", true); }
    refreshKeyStatus();
  });

  try {
    const [presets, upcoming] = await Promise.all([api("/api/presets"), fetch("/static/upcoming.json").then((r) => r.json()).catch(() => [])]);
    state.presets = presets;
    state.upcoming = upcoming;
    const total = presets.length + upcoming.length;
    const beta = presets.filter((x) => x.experimental).length;
    $("#liveCount").textContent = beta ? `${total} effects / ${beta} in beta` : `${presets.length} live / ${total}`;
    $("#heroCount").textContent = `Browse ${total} effects`;
    renderChips();
    renderRail();
    if (presets[0]) selectPreset(presets[0].id);
  } catch (err) { toast(`Could not load effects: ${err.message}`, true); }
  refreshKeyStatus();
}

init();
