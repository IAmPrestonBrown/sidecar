"use strict";

// View state. The server is authoritative; every snapshot replaces this.
const state = {
  phase: "prestart",
  interviewee: "",
  planned: 30,
  elapsed: 0,
  status: {},
  mapping: {},
  talk: null,
  transcript: [],
  interim: "",
  cards: { current: [], history: [], quiet_since: null },
  evidence: [],
  pinned: null,
  pinnedRunning: null,
  busy: { mark: false, ask_next: false },
  preflight: [],
  cost: 0,
  wsUp: false,
};

const MAX_TURNS = 8;
const DIM_AFTER_QUIET_S = 45;
const DIM_KEEP_LISTENING_S = 15;
const TALK_WARN = 0.4;

const $ = (id) => document.getElementById(id);

function esc(text) {
  const d = document.createElement("div");
  d.textContent = text == null ? "" : String(text);
  return d.innerHTML;
}

function mmss(sec) {
  const s = Math.max(0, Math.floor(sec));
  return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
}

// Websocket with automatic reconnect.
let ws = null;
let backoff = 500;

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => {
    backoff = 500;
    state.wsUp = true;
    renderStatus();
  };
  ws.onmessage = (ev) => {
    try {
      handle(JSON.parse(ev.data));
    } catch (err) {
      console.error("bad event", err);
    }
  };
  ws.onclose = () => {
    state.wsUp = false;
    renderStatus();
    setTimeout(connect, backoff);
    backoff = Math.min(5000, backoff * 2);
  };
}

function send(type) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type }));
}

function handle(ev) {
  switch (ev.type) {
    case "snapshot":
      state.phase = ev.phase;
      state.interviewee = ev.interviewee;
      state.planned = ev.planned_minutes;
      state.elapsed = ev.elapsed;
      state.status = ev.status;
      state.mapping = ev.mapping;
      state.talk = ev.talk_recent;
      state.transcript = ev.transcript;
      state.interim = ev.interim;
      state.cards = ev.cards;
      state.evidence = ev.evidence;
      state.pinned = ev.pinned;
      state.busy = ev.busy;
      state.preflight = ev.preflight;
      state.cost = ev.cost;
      state.pinnedRunning = null;
      renderAll();
      break;
    case "status":
      state.status = ev.status;
      renderStatus();
      break;
    case "level":
      state.elapsed = ev.elapsed;
      $("meterfill").style.width = Math.min(100, ev.rms * 400) + "%";
      renderClock();
      break;
    case "talk":
      state.talk = ev.recent;
      renderStatus();
      break;
    case "interim":
      state.interim = ev.text;
      renderInterim();
      break;
    case "segment":
      state.transcript.push(ev.segment);
      trimTranscript();
      renderTranscript();
      break;
    case "mapping":
      state.mapping = ev.mapping;
      state.transcript = ev.transcript;
      renderStatus();
      renderTranscript();
      break;
    case "cards":
      state.cards = ev;
      renderCards();
      break;
    case "evidence":
      state.evidence.push(ev.item);
      renderEvidence();
      break;
    case "mark_result":
    case "ask_next_result":
      handleResult(ev);
      break;
    case "pinned":
      state.pinned = ev.pinned;
      renderPinned();
      break;
    case "busy":
      flashBusy(ev.what);
      break;
    case "cost":
      state.cost = ev.total;
      renderStatus();
      break;
    case "session_end":
      state.phase = ev.state === "ended" ? "ended" : "finalizing";
      $("end-title").textContent = ev.state === "ended" ? "Session saved" : "Finalizing";
      $("end-detail").textContent = ev.dir ? ev.dir : "Writing audio and transcripts. See the terminal for progress.";
      renderPhase();
      break;
  }
}

function handleResult(ev) {
  const what = ev.type === "mark_result" ? "mark" : "ask_next";
  if (ev.state === "running") {
    state.busy[what] = true;
    state.pinnedRunning = { what, at: ev.at };
  } else {
    state.busy[what] = false;
    if (state.pinnedRunning && state.pinnedRunning.what === what) state.pinnedRunning = null;
    if (ev.state === "done") state.pinned = ev.result;
    if (ev.state === "error") state.pinnedRunning = { what, error: ev.detail || "failed" };
  }
  renderPinned();
  renderButtons();
}

function trimTranscript() {
  let turns = 0;
  let last = null;
  for (let i = state.transcript.length - 1; i >= 0; i--) {
    const label = state.transcript[i].label;
    if (label !== last) {
      turns += 1;
      last = label;
      if (turns > MAX_TURNS) {
        state.transcript = state.transcript.slice(i + 1);
        return;
      }
    }
  }
}

// Rendering

function renderAll() {
  renderPhase();
  renderStatus();
  renderClock();
  renderPinned();
  renderCards();
  renderEvidence();
  renderTranscript();
  renderInterim();
  renderButtons();
}

function renderPhase() {
  $("prestart").hidden = state.phase !== "prestart";
  $("ended").hidden = !(state.phase === "finalizing" || state.phase === "ended");
  $("rec").hidden = state.phase !== "recording";
  $("ps-title").textContent = `Interview: ${state.interviewee}`;
  $("ps-checks").innerHTML = state.preflight
    .map((r) => {
      const tag = r.ok && !r.warn ? "PASS" : r.ok ? "WARN" : "FAIL";
      return `<li><span class="${tag}">${tag}</span> ${esc(r.name)}: ${esc(r.detail)}</li>`;
    })
    .join("");
}

function renderClock() {
  $("elapsed").textContent = mmss(state.elapsed);
  const left = state.planned - state.elapsed / 60;
  $("remaining").textContent = left >= 0 ? `${Math.ceil(left)} min left` : `${Math.ceil(-left)} min over`;
}

function statusText(name, st) {
  if (!st) return { text: "", cls: "" };
  const lat = st.latency != null ? ` ${st.latency.toFixed(1)}s` : "";
  const good = ["ok", "live"];
  const warn = ["connecting", "reconnecting", "slow", "overflow", "idle"];
  const cls = good.includes(st.state) ? "good" : warn.includes(st.state) ? "warn" : "bad";
  const detail = st.detail && cls !== "good" ? ` (${st.detail})` : "";
  return { text: `${name} ${st.state}${lat}${detail}`, cls };
}

function setSt(id, info) {
  const el = $(id);
  el.textContent = info.text;
  el.className = "st " + info.cls;
}

function renderStatus() {
  $("who").textContent = state.interviewee;
  setSt("st-mic", statusText("MIC", state.status.mic));
  setSt("st-stt", statusText("STT", state.status.stt));
  setSt("st-coach", statusText("COACH", state.status.coach));
  setSt("st-ui", state.wsUp ? { text: "", cls: "" } : { text: "UI DISCONNECTED", cls: "bad" });
  if (state.talk == null) {
    setSt("talk", { text: "talk --", cls: "" });
  } else {
    const pct = Math.round(state.talk * 100);
    setSt("talk", { text: `you ${pct}% (3m)`, cls: state.talk > TALK_WARN ? "warn" : "" });
  }
  const m = state.mapping || {};
  const mapText = !m.mapped ? "speakers: unmapped" : m.locked ? "speakers: locked" : "speakers: provisional";
  setSt("mapping", { text: mapText, cls: m.mapped ? "" : "warn" });
  $("cost").textContent = state.cost ? `$${state.cost.toFixed(2)}` : "";
}

function cardHtml(c, withAt) {
  const ask = c.ask ? `<div class="ask">${esc(c.ask)}</div>` : "";
  const at = withAt ? `<span class="at">${esc(c.at)}</span>` : "";
  return `<div class="card k-${esc(c.kind)}" data-id="${esc(c.id)}">
    <div class="head"><span class="label kind">${esc(c.kind.replace(/_/g, " "))}</span>
    <span class="headline">${esc(c.headline)}</span>${at}</div>
    ${ask}<div class="why">${esc(c.why)}</div></div>`;
}

function renderCards() {
  const cur = state.cards.current || [];
  $("cards").innerHTML = cur.length
    ? cur.map((c) => cardHtml(c, true)).join("")
    : `<div class="empty">Quiet. Keep listening.</div>`;
  const hist = state.cards.history || [];
  $("history").innerHTML = hist.length ? hist.map((c) => cardHtml(c, true)).join("") : `<div class="empty">None.</div>`;
  applyDim();
}

function applyDim() {
  const now = Date.now() / 1000;
  const quiet = state.cards.quiet_since;
  for (const c of state.cards.current || []) {
    const el = document.querySelector(`#cards .card[data-id="${CSS.escape(c.id)}"]`);
    if (!el) continue;
    const age = now - c.shown_at;
    const dim =
      (c.kind === "KEEP_LISTENING" && age > DIM_KEEP_LISTENING_S) ||
      (quiet != null && age > DIM_AFTER_QUIET_S);
    el.classList.toggle("dim", dim);
  }
}

function renderPinned() {
  const box = $("pinned");
  const run = state.pinnedRunning;
  const p = state.pinned;
  if (!p && !run) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  let html = "";
  if (run) {
    const name = run.what === "mark" ? "MARK" : "ASK NEXT";
    html += run.error
      ? `<div class="pin-why">${name} failed: ${esc(run.error)}</div>`
      : `<div class="pin-why">${name} running...</div>`;
  }
  if (p) {
    $("pin-kind").textContent = p.kind === "mark" ? "MARK" : "ASK NEXT";
    $("pin-at").textContent = p.at || "";
    if (p.kind === "ask_next") {
      html += `<div class="pin-ask">${esc(p.ask)}</div><div class="pin-why">${esc(p.why)}</div>`;
    } else {
      const hyps = (p.hypotheses || []).map((h) => `${h.direction} ${h.id}`).join(", ") || "none";
      html += `<div class="headline"><b>${esc(p.headline)}</b></div>
        <div class="pin-ask">${esc(p.ask)}</div><div class="pin-why">${esc(p.why)}</div>
        <dl class="pin-grid">
          <dt>claim</dt><dd>${esc(p.claim)}</dd>
          <dt>type</dt><dd>${esc(p.evidence_type)}</dd>
          <dt>hyp</dt><dd>${esc(hyps)}</dd>
          ${p.contradiction ? `<dt>contra</dt><dd>${esc(p.contradiction)}</dd>` : ""}
          <dt>unknown</dt><dd>${esc(p.unknown)}</dd>
        </dl>`;
    }
  } else {
    $("pin-kind").textContent = "";
    $("pin-at").textContent = "";
  }
  $("pin-body").innerHTML = html;
}

function renderEvidence() {
  const items = state.evidence.slice().reverse();
  $("evidence").innerHTML = items.length
    ? items
        .map(
          (e) => `<div class="ev"><span class="at">${esc(e.at)}</span>
          <span class="stance ${esc(e.stance)}">${esc(e.stance)} ${esc((e.hypotheses || []).join(" "))}</span>
          <span class="muted small">${esc(e.type)}</span><div>${esc(e.note)}</div></div>`
        )
        .join("")
    : `<div class="empty">None yet.</div>`;
}

function renderTranscript() {
  const me = (state.mapping || {}).interviewer;
  const them = (state.mapping || {}).them;
  const turns = [];
  for (const s of state.transcript) {
    const last = turns[turns.length - 1];
    if (!s.gap && last && !last.gap && last.label === s.label) {
      last.text += " " + s.text;
    } else {
      turns.push({ ...s });
    }
  }
  $("transcript").innerHTML = turns
    .map((t) => {
      if (t.gap) return `<div class="turn gap"><span class="t">${esc(t.start)}</span>${esc(t.text)}</div>`;
      const cls = t.label === me ? "me" : t.label === them ? "them" : "";
      return `<div class="turn ${cls}"><span class="t">${esc(t.start)}</span><span class="who-l">${esc(t.label)}:</span>${esc(t.text)}</div>`;
    })
    .join("");
  const box = $("transcript-scroll");
  box.scrollTop = box.scrollHeight;
}

function renderInterim() {
  $("interim").textContent = state.interim || "";
  const box = $("transcript-scroll");
  box.scrollTop = box.scrollHeight;
}

function renderButtons() {
  const rec = state.phase === "recording";
  $("btn-mark").disabled = !rec;
  $("btn-ask").disabled = !rec;
  $("btn-swap").disabled = !rec;
  $("btn-end").disabled = !(rec || state.phase === "prestart");
  $("btn-mark").classList.toggle("busy", !!state.busy.mark);
  $("btn-ask").classList.toggle("busy", !!state.busy.ask_next);
}

function flashBusy(what) {
  state.pinnedRunning = { what, at: "" };
  renderPinned();
}

// Controls

function doMark() { if (state.phase === "recording") send("mark"); }
function doAsk() { if (state.phase === "recording") send("ask_next"); }
function doSwap() { if (state.phase === "recording") send("swap_speakers"); }
function doDismiss() {
  state.pinned = null;
  state.pinnedRunning = null;
  renderPinned();
  send("dismiss_pinned");
}
function doStart() { if (state.phase === "prestart") send("start"); }

let endTimer = null;
function doEnd() {
  const btn = $("btn-end");
  if (endTimer) {
    clearTimeout(endTimer);
    endTimer = null;
    btn.classList.remove("confirm");
    btn.textContent = "End";
    send("end_confirm");
    return;
  }
  send("end_request");
  btn.classList.add("confirm");
  btn.textContent = "Confirm end";
  endTimer = setTimeout(() => {
    endTimer = null;
    btn.classList.remove("confirm");
    btn.textContent = "End";
  }, 3000);
}

$("btn-mark").addEventListener("click", doMark);
$("btn-ask").addEventListener("click", doAsk);
$("btn-swap").addEventListener("click", doSwap);
$("btn-end").addEventListener("click", doEnd);
$("btn-start").addEventListener("click", doStart);

document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
  const k = e.key;
  if (k === "Enter" && state.phase === "prestart") { e.preventDefault(); doStart(); return; }
  if (k === "Escape") { doDismiss(); return; }
  const lower = k.toLowerCase();
  if (lower === "m") doMark();
  else if (lower === "q") doAsk();
  else if (lower === "s") doSwap();
});

setInterval(applyDim, 1000);
connect();
