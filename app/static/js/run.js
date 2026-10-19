// Run page: live progress over SSE, then the report, the evidence behind each citation,
// the claims (kept and removed) and the audit trail.

const root = document.getElementById("run-root");
const runId = root.dataset.runId;
const state = { run: null, report: null, claims: null, claimById: {}, refBySource: {}, tierBySource: {}, filter: "all", selected: null };

// Pipeline nodes -> the six steps shown to the reader. A loop-back (gap_plan) is more research.
const STEP_OF = { plan: "plan", gap_plan: "research", research: "research", draft: "draft", verify: "verify", cross_check: "cross", synthesize: "write", cite_check: "write" };
const NODE_LABEL = { plan: "Plan", gap_plan: "More research", research: "Research", draft: "Draft", verify: "Verify", cross_check: "Compare sources", synthesize: "Write", cite_check: "Citation check" };
const NODE_ICON = { plan: "route", gap_plan: "repeat-2", research: "search", draft: "pen-line", verify: "shield-check", cross_check: "scale", synthesize: "book-open-text", cite_check: "list-checks" };
const VERDICT = {
  SUPPORTED: { text: "Supported", pill: "pill-mint", icon: "circle-check" },
  PARTIAL: { text: "Narrowed to what the source says", pill: "pill-apricot", icon: "circle-alert" },
  UNSUPPORTED: { text: "Not supported", pill: "pill-rose", icon: "circle-x" },
  CONTRADICTED: { text: "Contradicted", pill: "pill-rose", icon: "circle-x" },
};
const TIER = {
  official: { text: "Official", pill: "pill-sky", icon: "landmark" },
  academic: { text: "Academic", pill: "pill-lavender", icon: "graduation-cap" },
  news: { text: "News", pill: "pill-apricot", icon: "newspaper" },
  other: { text: "Web", pill: "", icon: "globe" },
  file: { text: "Your document", pill: "pill-sky", icon: "file-text" },
};

// ------------------------------------------------------------------ tabs
function showTab(name) {
  document.querySelectorAll("[role=tab]").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("hidden", p.id !== `panel-${name}`));
}
document.querySelectorAll("[role=tab]").forEach((tab) => tab.addEventListener("click", () => showTab(tab.dataset.tab)));

// ------------------------------------------------------------------ status + progress
const pipeline = document.getElementById("pipeline");
const liveNote = document.getElementById("live-note");

function setStatus(kind, text) {
  const pill = document.getElementById("run-status");
  const look = { running: ["pill-lavender", "loader-circle", "spin"], done: ["pill-mint", "circle-check", ""], failed: ["pill-rose", "circle-x", ""] }[kind];
  pill.className = `pill ${look[0]}`;
  pill.replaceChildren(icon(look[1], `icon-sm ${look[2]}`), text);
}

function markStep(step, cls) {
  const li = pipeline.querySelector(`[data-step="${step}"]`);
  if (!li) return;
  if (cls === "active") {
    pipeline.querySelectorAll(".step.active").forEach((x) => { if (x !== li) { x.classList.remove("active"); x.classList.add("done"); } });
    li.classList.remove("done");
  }
  li.classList.add(cls);
  if (cls === "done") li.classList.remove("active");
}

function setLiveNote(text) {
  liveNote.replaceChildren(icon("loader-circle", "icon-sm spin"), el("span", {}, text));
}

function onTrailEvent(ev) {
  appendTrail(ev);
  if (ev.tokens) scheduleTokenRefresh();
  const node = ev.node.split(":")[0];
  const step = STEP_OF[node];
  if (!step) return;
  if (ev.phase === "start") {
    markStep(step, "active");
    setStatus("running", `${NODE_LABEL[node] || "Working"}…`);
  } else if (ev.phase === "end") {
    if (node !== "research") markStep(step, "done");
    if (ev.summary) setLiveNote(ev.summary);
  } else if (ev.phase === "error") {
    markStep(step, "failed");
  }
}

function listenForProgress() {
  const source = new EventSource(`/api/runs/${runId}/events`);
  source.addEventListener("trail", (e) => onTrailEvent(JSON.parse(e.data)));
  source.addEventListener("done", (e) => {
    source.close();
    const info = JSON.parse(e.data);
    pipeline.querySelectorAll(".step.active").forEach((x) => { x.classList.remove("active"); x.classList.add(info.status === "done" ? "done" : "failed"); });
    document.getElementById("progress").classList.add("finished");
    refreshTokens();
    if (info.status === "done") loadResults();
    else showFailure(info.error);
  });
  source.onerror = () => { /* the browser reconnects automatically */ };
}

// ------------------------------------------------------------------ failure
function friendlyError(error) {
  const e = String(error || "");
  if (/no evidence|no search results|NoEvidence/i.test(e)) return "No usable sources were found for this question. Try naming the place, year or organisation you mean.";
  if (/balance|402|spend cap/i.test(e)) return "The model credit balance is too low to finish this run. Top up the Mesh balance, then run it again.";
  if (/budget/i.test(e)) return "The run reached its cost limit before finishing. Try the Quick setting or a narrower question.";
  return e || "Something went wrong. The audit trail shows the last step that ran.";
}

async function showFailure(error) {
  setStatus("failed", "Stopped");
  const run = await api(`/api/runs/${runId}`).catch(() => null);
  const card = el("div", { class: "state-card" },
    el("span", { class: "bubble pill-rose" }, icon("triangle-alert")),
    el("div", {},
      el("h2", {}, "This research didn't finish"),
      el("p", {}, friendlyError(error || run?.error)),
      run ? el("button", { class: "btn", type: "button", onclick: () => rerun(run) }, icon("repeat-2"), "Run again") : null));
  document.getElementById("report-waiting").replaceWith(card);
}

async function rerun(run) {
  try {
    const next = await api("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: run.question, depth: run.depth, file_ids: [] }) });
    window.location.href = `/runs/${next.run_id}`;
  } catch (err) { setLiveNote(`Could not start again: ${err.message}`); }
}

// ------------------------------------------------------------------ audit trail
const trailEl = document.getElementById("trail");

function appendTrail(ev) {
  if (ev.phase === "start") return; // finished steps only, so the trail stays readable
  const node = ev.node.split(":")[0];
  const meta = [ev.latency_ms ? `${(ev.latency_ms / 1000).toFixed(1)} s` : null, ev.models || null].filter(Boolean).join(", ");
  const hasPayload = ev.payload && Object.keys(ev.payload).length > 0;
  const failed = ev.phase === "error";
  trailEl.append(el("li", {},
    el("span", { class: `status-icon ${failed ? "status-failed" : "status-done"}` }, icon(failed ? "x" : NODE_ICON[node] || "check", "icon-sm")),
    el("div", { class: "trail-main" },
      el("div", { class: "trail-top" },
        el("span", { class: "trail-node" }, NODE_LABEL[node] || ev.node),
        el("span", {}, ev.summary),
        meta ? el("span", { class: "trail-meta" }, meta) : null),
      hasPayload ? el("details", {}, el("summary", {}, "Details"),
        el("pre", {}, JSON.stringify(ev.payload, null, 2))) : null)));
}

// ------------------------------------------------------------------ dev token view
const devMode = root.dataset.dev === "true";
let tokenTimer = null;
async function refreshTokens() {
  if (!devMode) return;
  try { renderRunTokens(document.getElementById("tokens"), await api(`/api/runs/${runId}/usage`)); } catch (_) { /* best-effort */ }
}
function scheduleTokenRefresh() {
  if (!devMode || tokenTimer) return;
  tokenTimer = setTimeout(() => { tokenTimer = null; refreshTokens(); }, 1200);
}

// ------------------------------------------------------------------ evidence (the highlighted passage)
// Normalise whitespace and case but remember where each character came from, so the match
// can be highlighted in the original text.
function normWithMap(text) {
  let out = "";
  const map = [];
  let space = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (/\s/.test(ch)) { if (!space && out) { out += " "; map.push(i); } space = true; continue; }
    space = false;
    out += ch.toLowerCase().replace(/[‘’]/g, "'").replace(/[“”]/g, '"');
    map.push(i);
  }
  return { out, map };
}

function findQuoteRanges(text, quote) {
  if (!quote) return [];
  const { out, map } = normWithMap(text);
  const ranges = [];
  let from = 0;
  for (const part of quote.split(/\s*(?:\.\.\.|…)\s*/)) {
    const p = normWithMap(part.trim().replace(/^["“]|["”]$/g, "")).out;
    if (p.length < 4) continue;
    const at = out.indexOf(p, from);
    if (at === -1) continue;
    ranges.push([map[at], map[at + p.length - 1] + 1]);
    from = at + p.length;
  }
  return ranges;
}

function highlighted(text, quote) {
  const ranges = findQuoteRanges(text, quote);
  if (!ranges.length) return { node: el("div", { class: "ev-passage" }, text), found: false };
  const parts = [];
  let pos = 0;
  for (const [a, b] of ranges) {
    parts.push(text.slice(pos, a), el("mark", {}, text.slice(a, b)));
    pos = b;
  }
  parts.push(text.slice(pos));
  return { node: el("div", { class: "ev-passage" }, parts), found: true };
}

function tierOf(source) {
  if (!source) return TIER.other;
  if (source.kind === "file") return TIER.file;
  return TIER[source.tier] || TIER.other;
}

function tierPill(source) {
  const t = tierOf(source);
  return el("span", { class: `pill ${t.pill}` }, icon(t.icon, "icon-sm"), t.text);
}

function verdictNote(v) {
  if (!v) return null;
  if (v.model === "code:verbatim") return "The sentence appears word for word in the source.";
  if (v.model === "code:official-source") return v.reason;
  return v.reason || null;
}

function evidenceContent(claim) {
  const v = claim.verdict || {};
  const look = VERDICT[v.label] || { text: "Not checked", pill: "", icon: "circle-alert" };
  const nodes = [
    el("div", { class: "ev-head" }, el("span", { class: `pill ${look.pill}` }, icon(look.icon, "icon-sm"), look.text)),
    el("p", { class: "ev-claim" }, claim.text),
  ];
  const note = verdictNote(v);
  if (note) nodes.push(el("p", { class: "ev-reason" }, note));
  let shown = false;
  for (const chunk of claim.chunks) {
    const src = chunk.source;
    const href = src ? safeUrl(src.url) : null;
    const title = src ? (src.title || src.domain || "Source") : "Source";
    const { node, found } = highlighted(chunk.text, v.evidence_quote);
    shown = shown || found;
    nodes.push(el("div", { class: "ev-source" },
      el("div", { class: "ev-source-title" },
        href ? el("a", { href, target: "_blank", rel: "noopener noreferrer" }, title, " ", icon("external-link", "icon-sm")) : el("span", {}, title)),
      el("div", { class: "ev-source-sub" }, tierPill(src),
        src?.domain ? el("span", { class: "pill" }, src.domain) : null,
        chunk.page ? el("span", { class: "pill" }, `Page ${chunk.page}`) : null,
        state.refBySource[chunk.source_id] ? el("span", { class: "pill" }, `Reference ${state.refBySource[chunk.source_id]}`) : null),
      node));
  }
  if (v.evidence_quote && !shown) {
    nodes.splice(3, 0, el("p", { class: "ev-quote" }, `“${v.evidence_quote}”`));
  }
  return nodes;
}

const wide = matchMedia("(min-width: 1101px)");
const sheet = document.getElementById("evidence-sheet");
document.getElementById("sheet-close").addEventListener("click", () => sheet.close());
sheet.addEventListener("click", (e) => { if (e.target === sheet) sheet.close(); }); // tap outside closes

function openEvidence(claim, trigger) {
  document.querySelectorAll(".cite[aria-pressed=true]").forEach((b) => b.setAttribute("aria-pressed", "false"));
  document.querySelectorAll(".sentence.selected").forEach((s) => s.classList.remove("selected"));
  if (trigger) {
    trigger.setAttribute("aria-pressed", "true");
    trigger.closest(".sentence")?.classList.add("selected");
  }
  let box;
  if (wide.matches) {
    box = document.getElementById("evidence");
    box.replaceChildren(...evidenceContent(claim));
    box.scrollTop = 0;
  } else {
    box = document.getElementById("sheet-body");
    box.replaceChildren(...evidenceContent(claim));
    sheet.showModal();
  }
  // Bring the highlighted words into view inside their passage (the passage scrolls, not the page).
  box.querySelectorAll(".ev-passage").forEach((passage) => {
    const mark = passage.querySelector("mark");
    if (mark) passage.scrollTop = Math.max(0, mark.offsetTop - 24); // .ev-passage is the offset parent
  });
}

// ------------------------------------------------------------------ report
function citeMarks(sentence) {
  return sentence.claim_ids.map((cid) => state.claimById[cid]).filter(Boolean).map((claim) => {
    const nums = [...new Set(claim.chunks.map((c) => state.refBySource[c.source_id]).filter(Boolean))].sort((a, b) => a - b);
    const narrowed = Boolean(claim.parent_claim_id);
    return el("button", {
      type: "button",
      class: `cite${narrowed ? " narrowed" : ""}`,
      "aria-pressed": "false",
      "aria-label": `Show evidence from source ${nums.join(", ") || ""}`.trim(),
      title: narrowed ? "Verified after narrowing to what the source says" : "Verified against the cited source",
      onclick: (e) => openEvidence(claim, e.currentTarget),
    }, nums.length ? nums.join(",") : "src");
  });
}

function sentenceNode(sentence) {
  return el("span", { class: "sentence" }, sentence.text, ...citeMarks(sentence), " ");
}

function renderReport() {
  const r = state.report;
  const article = document.getElementById("report");
  article.replaceChildren(
    el("h2", {}, "Summary"),
    el("div", { class: "summary" }, r.executive_summary.map((s) => el("p", {}, sentenceNode(s)))));
  for (const section of r.sections) {
    article.append(el("h2", {}, section.heading));
    if (section.limited_evidence) {
      article.append(el("p", { class: "note note-limited" }, icon("triangle-alert", "icon-sm"),
        el("span", {}, "Limited evidence: fewer than two verified claims from two independent sources.")));
    }
    article.append(section.sentences.length
      ? el("p", {}, section.sentences.map(sentenceNode))
      : el("p", { class: "empty-section" }, "No claim for this part passed verification."));
  }
  if (r.disagreements.length) {
    article.append(el("h2", {}, "Where sources disagree"),
      el("ul", { class: "plain" }, r.disagreements.map((d) => el("li", {},
        d.superseded_claim ? `${d.explanation} The non-official claim was removed because an official source contradicts it.` : d.explanation))));
  }
  if (r.limitations.length) {
    article.append(el("h2", {}, "Limitations"), el("ul", { class: "plain" }, r.limitations.map((t) => el("li", {}, t))));
  }
  article.append(el("h2", {}, "References"), el("ol", { class: "refs" }, r.references.map((ref) => {
    const href = safeUrl(ref.url);
    const src = { tier: state.tierBySource[ref.source_id] };
    return el("li", {},
      el("span", { class: "num" }, String(ref.number)),
      el("div", { class: "ref-main" },
        el("div", { class: "ref-title" }, href ? el("a", { href, target: "_blank", rel: "noopener noreferrer" }, ref.title || ref.domain) : (ref.title || ref.domain)),
        el("div", { class: "ref-sub" }, tierPill(src), el("span", {}, ref.domain), ref.page ? el("span", {}, `page ${ref.page}`) : null)));
  })));
  document.getElementById("report-waiting").classList.add("hidden");
  article.classList.remove("hidden");
}

// ------------------------------------------------------------------ claims
function renderClaims() {
  const wrap = document.getElementById("claims");
  wrap.replaceChildren();
  const visible = state.claims.claims.filter((c) => state.filter === "all" || (state.filter === "kept" ? c.kept : !c.kept));
  for (const sq of state.claims.sub_questions) {
    const rows = visible.filter((c) => c.sub_question_id === sq.id);
    if (!rows.length) continue;
    wrap.append(el("div", { class: "claims-group" }, el("h3", {}, sq.text), rows.map((c) => {
      const v = c.verdict || {};
      const reason = c.parent_claim_id ? `Narrowed claim. ${v.reason || ""}` : verdictNote(v);
      return el("div", { class: `claim${c.kept ? "" : " removed"}` },
        el("span", { class: `status-icon ${c.kept ? "status-done" : "status-failed"}`, title: c.kept ? "Kept" : "Removed" }, icon(c.kept ? "check" : "x", "icon-sm")),
        el("div", { class: "claim-main" }, el("p", { class: "claim-text" }, c.text), reason ? el("p", { class: "claim-reason" }, reason) : null),
        el("button", { type: "button", class: "btn", onclick: () => openEvidence(c) }, icon("quote", "icon-sm"), "Evidence"));
    })));
  }
  if (!wrap.children.length) {
    wrap.append(el("p", { class: "empty" }, state.filter === "rejected" ? "The verifier removed no claims in this run." : "No claims match this filter."));
  }
}

document.querySelectorAll("[data-filter]").forEach((btn) => btn.addEventListener("click", () => setFilter(btn.dataset.filter)));
function setFilter(filter) {
  state.filter = filter;
  document.querySelectorAll("[data-filter]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.filter === filter)));
  renderClaims();
}

// ------------------------------------------------------------------ summary chips + load
function utc(iso) { return new Date(/Z|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`); } // stored times are UTC

function renderMeta() {
  const all = state.claims.claims;
  const kept = all.filter((c) => c.kept).length;
  const removed = all.length - kept;
  document.getElementById("claims-count").textContent = String(all.length);
  setStatus("done", "Report ready");
  document.getElementById("run-meta").append(
    el("span", { class: "pill pill-mint", title: "Claims that passed verification" }, icon("shield-check", "icon-sm"), `${kept} verified`),
    el("button", { type: "button", class: "pill pill-rose", title: "Show the claims the verifier removed",
      onclick: () => { showTab("claims"); setFilter("rejected"); } }, icon("eraser", "icon-sm"), `${removed} removed`),
    el("span", { class: "pill pill-sky", title: "Sources cited in the report" }, icon("globe", "icon-sm"), `${state.report.references.length} sources`),
    state.run?.finished_at && state.run?.created_at
      ? el("span", { class: "pill", title: "Time the research took" }, icon("history", "icon-sm"), `${Math.max(1, Math.round((utc(state.run.finished_at) - utc(state.run.created_at)) / 1000))} s`)
      : null);
}

async function loadResults() {
  try {
    const [report, claims, run] = await Promise.all([
      api(`/api/runs/${runId}/report`), api(`/api/runs/${runId}/claims`), api(`/api/runs/${runId}`)]);
    state.report = report;
    state.claims = claims;
    state.run = run;
    state.claimById = Object.fromEntries(claims.claims.map((c) => [c.id, c]));
    state.refBySource = Object.fromEntries(report.references.map((r) => [r.source_id, r.number]));
    for (const c of claims.claims) for (const ch of c.chunks) if (ch.source) state.tierBySource[ch.source_id] = ch.source.kind === "file" ? "file" : ch.source.tier;
    renderReport();
    renderClaims();
    renderMeta();
    document.getElementById("export-md").classList.remove("hidden");
    document.getElementById("export-html").classList.remove("hidden");
  } catch (err) {
    showFailure(`Could not load the report: ${err.message}`);
  }
}

if (root.dataset.status === "done") setStatus("done", "Loading report…");
refreshTokens();
listenForProgress(); // replays the stored trail, then follows live events until the run ends
