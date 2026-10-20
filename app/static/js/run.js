// Run page: live progress over SSE, then the report, the evidence behind each citation,
// the claims (kept and removed) and the audit trail.

const root = document.getElementById("run-root");
const runId = root.dataset.runId;
const state = { run: null, report: null, claims: null, claimById: {}, refBySource: {}, tierBySource: {}, filter: "all", selected: null, unverified: false };

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
// Runs with verification switched off (the evaluation's ablation) keep every claim unchecked. Their
// stored verdicts say SUPPORTED with model "none"; they must never look verified.
const NOT_VERIFIED = { text: "Not verified", pill: "", icon: "circle-alert" };
const NOT_VERIFIED_NOTE = "Verification was turned off for this run (an evaluation comparison), so this claim was not checked against its source.";
const isUnchecked = (v) => !!v && v.model === "none";
const TIER = {
  official: { text: "Official", pill: "pill-sky", icon: "landmark" },
  academic: { text: "Academic", pill: "pill-lavender", icon: "graduation-cap" },
  news: { text: "News", pill: "pill-apricot", icon: "newspaper" },
  other: { text: "Web", pill: "", icon: "globe" },
  file: { text: "Your document", pill: "pill-sky", icon: "file-text" },
};

// ------------------------------------------------------------------ tabs
const tabs = [...document.querySelectorAll("[role=tab]")];
function showTab(name, focus = false) {
  tabs.forEach((t) => {
    const on = t.dataset.tab === name;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1; // roving tabindex: one tab stop for the tab list, arrows move inside it
    if (on && focus) t.focus();
  });
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("hidden", p.id !== `panel-${name}`));
}
tabs.forEach((tab) => {
  tab.addEventListener("click", () => showTab(tab.dataset.tab));
  tab.addEventListener("keydown", (e) => {
    const i = tabs.indexOf(tab);
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    showTab(tabs[(next + tabs.length) % tabs.length].dataset.tab, true);
  });
});
showTab("report");

// ------------------------------------------------------------------ status + progress
const pipeline = document.getElementById("pipeline");
const liveNote = document.getElementById("live-note");

function setStatus(kind, text) {
  const pill = document.getElementById("run-status");
  const look = { running: ["pill-lavender", "loader-circle", "spin"], done: ["pill-mint", "circle-check", ""], failed: ["pill-rose", "circle-x", ""],
    stopped: ["", "circle-stop", ""] }[kind];
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
    if (node === "plan" && ev.payload?.researched_as) showResearchedAs(ev.payload.researched_as);
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
    const ended = { done: "done", stopped: "stopped" }[info.status] || "failed";
    pipeline.querySelectorAll(".step.active").forEach((x) => { x.classList.remove("active"); x.classList.add(ended); });
    if (ended === "failed" && !pipeline.querySelector(".step.failed")) {
      pipeline.querySelector(".step:not(.done)")?.classList.add("failed"); // the step the run stopped at
    }
    document.getElementById("progress").classList.add("finished");
    document.getElementById("stop-run").classList.add("hidden");
    document.getElementById("edit-toggle").classList.remove("hidden"); // edit & run again, once finished
    refreshTokens();
    if (info.status === "done") loadResults();
    else if (info.status === "stopped") showStopped();
    else showFailure(info.error);
  });
  source.onerror = () => { /* the browser reconnects automatically */ };
}

// ------------------------------------------------------------------ failure
function friendlyError(error) {
  const e = String(error || "");
  if (/no evidence|no search results|no sources found|NoEvidence/i.test(e)) return "No usable sources were found for this question. Try naming the place, year or organisation you mean, or check that web search is set up.";
  if (/connection error|connecterror|proxyerror|timed out|timeout|unreachable/i.test(e)) return "DeepDive could not reach the AI model service. Check the internet connection and the Mesh API key, then run it again.";
  if (/did not return valid|invalid json/i.test(e)) return "The AI model returned an answer DeepDive could not read. Running it again usually works.";
  if (/balance|402|spend cap/i.test(e)) return "The model credit balance is too low to finish this run. Top up the Mesh balance, then run it again.";
  if (/budget/i.test(e)) return "The run reached its cost limit before finishing. Try the Quick setting or a narrower question.";
  return e ? `Something went wrong: ${e}` : "Something went wrong. The audit trail shows the last step that ran.";
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
  document.getElementById("evidence").classList.add("hidden"); // nothing to cite on a failed run
  liveNote.replaceChildren();
}

// ------------------------------------------------------------------ stop (before the next step)
let stoppedHere = false; // pressed Stop on this page: keep the editor open for the corrected question
const stopBtn = document.getElementById("stop-run");

function setStopButton(label, disabled) {
  stopBtn.disabled = disabled;
  stopBtn.querySelector("span").textContent = label;
}

stopBtn.addEventListener("click", async () => {
  setStopButton("Stopping…", true);
  try {
    await api(`/api/runs/${runId}/stop`, { method: "POST", headers: accessHeaders() });
    stoppedHere = true;
    setLiveNote("Stopping after the current step… You can edit the question now.");
    document.getElementById("edit-toggle").classList.remove("hidden");
    setEditOpen(true);
  } catch (err) {
    setStopButton("Stop", false);
    setLiveNote(`Could not stop: ${err.message}`);
  }
});

function showStopped() {
  setStatus("stopped", "Stopped");
  const card = el("div", { class: "state-card" },
    el("span", { class: "bubble pill-lavender" }, icon("circle-stop")),
    el("div", {},
      el("h2", {}, "You stopped this research"),
      el("p", {}, "No further steps were run. Edit the question and run it again: pages this run already searched and read are cached, so the new run reuses them wherever the corrected question needs them."),
      el("button", { class: "btn", type: "button", onclick: () => setEditOpen(true) }, icon("pen-line"), "Edit & run again")));
  document.getElementById("report-waiting").replaceWith(card);
  document.getElementById("evidence").classList.add("hidden"); // nothing to cite on a stopped run
  liveNote.replaceChildren();
  if (stoppedHere && editForm.classList.contains("hidden")) setEditOpen(true);
}

async function rerun(run) {
  try {
    const next = await api("/api/runs", { method: "POST", headers: accessHeaders({ "Content-Type": "application/json" }),
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
  const box = (children) => el("div", { class: "ev-passage", tabindex: "0", role: "region", "aria-label": "Source passage" }, children);
  if (!ranges.length) return { node: box(text), found: false };
  const parts = [];
  let pos = 0;
  for (const [a, b] of ranges) {
    parts.push(text.slice(pos, a), el("mark", {}, text.slice(a, b)));
    pos = b;
  }
  parts.push(text.slice(pos));
  return { node: box(parts), found: true };
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
  if (isUnchecked(v)) return NOT_VERIFIED_NOTE;
  if (v.model === "code:verbatim") return "The sentence appears word for word in the source.";
  if (v.model === "code:official-source") return v.reason;
  return v.reason || null;
}

function evidenceContent(claim) {
  const v = claim.verdict || {};
  const look = isUnchecked(v) ? NOT_VERIFIED : VERDICT[v.label] || { text: "Not checked", pill: "", icon: "circle-alert" };
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
  if (claim.kept && state.report) {
    nodes.push(el("div", { class: "ev-actions" },
      el("button", { type: "button", class: "btn", onclick: () => askAbout(claim) }, icon("message-square-plus", "icon-sm"), "Research this further")));
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
    const unchecked = isUnchecked(claim.verdict);
    return el("button", {
      type: "button",
      class: `cite${unchecked ? " unverified" : narrowed ? " narrowed" : ""}`,
      "aria-pressed": "false",
      "aria-label": `Show evidence from source ${nums.join(", ") || ""}`.trim(),
      title: unchecked ? "Not verified: verification was off for this run" : narrowed ? "Verified after narrowing to what the source says" : "Verified against the cited source",
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
    state.unverified ? el("p", { class: "note note-unverified" }, icon("circle-alert", "icon-sm"),
      el("span", {}, "Verification was turned off for this run, an evaluation comparison. Its claims were not checked against their sources.")) : "",
    el("h2", {}, "Summary"),
    el("div", { class: "summary" }, r.executive_summary.map((s) => el("p", {}, sentenceNode(s)))));
  for (const section of r.sections) {
    article.append(el("h2", {}, section.heading));
    if (section.limited_evidence) {
      article.append(el("p", { class: "note note-limited" }, icon("triangle-alert", "icon-sm"),
        el("span", {}, "Limited evidence: fewer than two verified claims from two independent sources.")));
    }
    const keptHere = state.claims?.claims.some((c) => c.kept && c.sub_question_id === section.sub_question_id);
    article.append(section.sentences.length
      ? el("p", {}, section.sentences.map(sentenceNode))
      : el("p", { class: "empty-section" }, keptHere
        ? "The verified claims for this part did not answer it directly, so none were written here. They are listed in the Claims tab."
        : "No claim for this part passed verification."));
  }
  if (r.disagreements.length) {
    article.append(el("h2", {}, "Where sources disagree"),
      el("ul", { class: "plain" }, r.disagreements.map((d) => el("li", {},
        d.superseded_claim ? `${d.explanation} The non-official claim was removed because an official source contradicts it.` : d.explanation))));
  }
  if (r.limitations.length) {
    article.append(el("h2", {}, "Limitations"), el("ul", { class: "plain" }, r.limitations.map((t) => el("li", {}, t))));
  }
  // References sit after the "Continue this research" box, in their own block with the report's styling.
  const refsBox = document.getElementById("report-refs");
  refsBox.replaceChildren(el("h2", {}, "References"), el("ol", { class: "refs" }, r.references.map((ref) => {
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
  refsBox.classList.remove("hidden");
}

// ------------------------------------------------------------------ claims
function renderClaims() {
  const wrap = document.getElementById("claims");
  wrap.replaceChildren();
  const visible = state.claims.claims.filter((c) => state.filter === "all" || (state.filter === "kept" ? c.kept : !c.kept));
  for (const sq of state.claims.sub_questions) {
    const rows = visible.filter((c) => c.sub_question_id === sq.id);
    if (!rows.length) continue;
    wrap.append(el("div", { class: "claims-group" }, el("h2", {}, sq.text), rows.map((c) => {
      const v = c.verdict || {};
      const unchecked = isUnchecked(v);
      const reason = c.parent_claim_id ? `Narrowed claim. ${v.reason || ""}` : verdictNote(v);
      const statusIcon = unchecked
        ? el("span", { class: "status-icon status-unverified", title: "Not verified" }, icon("circle-alert", "icon-sm"))
        : el("span", { class: `status-icon ${c.kept ? "status-done" : "status-failed"}`, title: c.kept ? "Kept" : "Removed" }, icon(c.kept ? "check" : "x", "icon-sm"));
      return el("div", { class: `claim${c.kept ? "" : " removed"}` },
        statusIcon,
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
  const took = state.run?.finished_at && state.run?.created_at
    ? el("span", { class: "pill", title: "Time the research took" }, icon("history", "icon-sm"), `${Math.max(1, Math.round((utc(state.run.finished_at) - utc(state.run.created_at)) / 1000))} s`)
    : null;
  if (state.unverified) {
    setStatus("done", "Report ready, not verified");
    document.getElementById("run-meta").append(
      el("span", { class: "pill", title: NOT_VERIFIED_NOTE }, icon("circle-alert", "icon-sm"), "Verification off"),
      el("span", { class: "pill", title: "Claims in this run, none checked" }, icon("list-checks", "icon-sm"), `${all.length} unchecked claims`),
      el("span", { class: "pill pill-sky", title: "Sources cited in the report" }, icon("globe", "icon-sm"), `${state.report.references.length} sources`),
      took);
    return;
  }
  setStatus("done", "Report ready");
  document.getElementById("run-meta").append(
    el("span", { class: "pill pill-mint", title: "Claims that passed verification" }, icon("shield-check", "icon-sm"), `${kept} verified`),
    el("button", { type: "button", class: "pill pill-rose", title: "Show the claims the verifier removed",
      onclick: () => { showTab("claims"); setFilter("rejected"); } }, icon("eraser", "icon-sm"), `${removed} removed`),
    el("span", { class: "pill pill-sky", title: "Sources cited in the report" }, icon("globe", "icon-sm"), `${state.report.references.length} sources`),
    took);
}

async function loadResults() {
  try {
    const [report, claims, run] = await Promise.all([
      api(`/api/runs/${runId}/report`), api(`/api/runs/${runId}/claims`), api(`/api/runs/${runId}`)]);
    state.report = report;
    state.claims = claims;
    state.run = run;
    state.claimById = Object.fromEntries(claims.claims.map((c) => [c.id, c]));
    state.unverified = claims.claims.length > 0 && claims.claims.every((c) => isUnchecked(c.verdict));
    state.refBySource = Object.fromEntries(report.references.map((r) => [r.source_id, r.number]));
    for (const c of claims.claims) for (const ch of c.chunks) if (ch.source) state.tierBySource[ch.source_id] = ch.source.kind === "file" ? "file" : ch.source.tier;
    renderReport();
    renderClaims();
    renderMeta();
    renderFollowUp();
    document.getElementById("export-md").classList.remove("hidden");
    document.getElementById("export-html").classList.remove("hidden");
  } catch (err) {
    showFailure(`Could not load the report: ${err.message}`);
  }
}

// ------------------------------------------------------------------ follow-up research (same thread)
const followUpBox = document.getElementById("followup-q");
const followUpStatus = document.getElementById("followup-status");
const followUpAccess = document.getElementById("followup-access");

function shorten(text, n) { return text.length > n ? `${text.slice(0, n - 1)}…` : text; }

function renderThread(run) {
  const nav = document.getElementById("thread");
  if (!run?.thread?.length) return;
  nav.replaceChildren(el("span", {}, "Follows"), ...run.thread.map((r) => el("a", { href: `/runs/${r.id}`, title: r.question },
    icon("corner-down-right", "icon-sm"), el("span", {}, shorten(r.question, 70)))));
  nav.classList.remove("hidden");
}

function showResearchedAs(question) {
  const p = document.getElementById("researched-as");
  if (!question || question.trim() === document.querySelector(".run-head h1").textContent.trim()) return;
  p.replaceChildren("Researched as: ", el("strong", {}, question));
  p.classList.remove("hidden");
}

// Suggested follow-ups: the parts of the question this report could only answer thinly.
function followUpSuggestions() {
  const kept = {};
  for (const c of state.claims.claims) if (c.kept) kept[c.sub_question_id] = (kept[c.sub_question_id] || 0) + 1;
  return state.claims.sub_questions.filter((sq) => (kept[sq.id] || 0) < 2).slice(0, 3)
    .map((sq) => `Find more evidence: ${sq.text.replace(/\?$/, "")}?`);
}

function renderFollowUp() {
  if (state.unverified) return; // evaluation comparison runs are not a starting point
  document.getElementById("followup-suggest").replaceChildren(...followUpSuggestions().map((q) =>
    el("button", { type: "button", class: "suggestion", onclick: () => { followUpBox.value = q; followUpBox.focus(); } }, q)));
  document.getElementById("followup-list").replaceChildren(...(state.run?.followups || []).map((r) =>
    el("a", { href: `/runs/${r.id}` }, el("span", { class: `status-icon status-${r.status}` },
      icon({ done: "check", failed: "x", stopped: "circle-stop" }[r.status] || "loader-circle", `icon-sm${["running", "queued", "stopping"].includes(r.status) ? " spin" : ""}`)),
      el("span", { class: "q" }, r.question), icon("corner-down-right", "icon-sm"))));
  document.getElementById("followup").classList.remove("hidden");
  api("/api/health").then((h) => { if (h.access_code_required && !getAccessCode()) followUpAccess.classList.remove("hidden"); }).catch(() => {});
}

function askAbout(claim) {
  if (sheet.open) sheet.close();
  showTab("report");
  followUpBox.value = `Tell me more about this: ${claim.text}`;
  document.getElementById("followup").scrollIntoView({ behavior: "smooth", block: "center" });
  followUpBox.focus({ preventScroll: true });
}

function setFollowUpStatus(text, error = false) {
  followUpStatus.className = `form-status${error ? " error" : ""}`;
  followUpStatus.replaceChildren(error ? icon("circle-alert", "icon-sm") : icon("loader-circle", "icon-sm spin"), text);
}

document.getElementById("followup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = followUpBox.value.trim();
  if (question.length < 5) { setFollowUpStatus("Write a follow-up question first (at least a few words).", true); followUpBox.focus(); return; }
  if (!followUpAccess.classList.contains("hidden") && followUpAccess.value.trim()) setAccessCode(followUpAccess.value.trim());
  const button = document.getElementById("followup-submit");
  button.disabled = true;
  setFollowUpStatus("Starting the follow-up…");
  try {
    const next = await api(`/api/runs/${runId}/followup`, { method: "POST", headers: accessHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ question }) });
    window.location.href = `/runs/${next.run_id}`;
  } catch (err) {
    if (/access code/i.test(err.message)) { followUpAccess.classList.remove("hidden"); followUpAccess.focus(); }
    setFollowUpStatus(`Could not start the follow-up: ${err.message}`, true);
    button.disabled = false;
  }
});
followUpBox.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) document.getElementById("followup-form").requestSubmit();
});

api(`/api/runs/${runId}`).then(renderThread).catch(() => {});

// ------------------------------------------------------------------ edit & run again (a new run; this one is kept)
const editForm = document.getElementById("edit-run");
const editToggle = document.getElementById("edit-toggle");
const editBox = document.getElementById("edit-q");
const editStatus = document.getElementById("edit-status");
const editAccess = document.getElementById("edit-access");

function setEditOpen(open) {
  editForm.classList.toggle("hidden", !open);
  editToggle.setAttribute("aria-expanded", String(open));
  if (open) {
    editBox.focus();
    editBox.setSelectionRange(editBox.value.length, editBox.value.length);
    api("/api/health").then((h) => { if (h.access_code_required && !getAccessCode()) editAccess.classList.remove("hidden"); }).catch(() => {});
  } else {
    editToggle.focus();
  }
}
function setEditStatus(text, error = false) {
  editStatus.className = `form-status${error ? " error" : ""}`;
  editStatus.replaceChildren(text ? icon(error ? "circle-alert" : "loader-circle", error ? "icon-sm" : "icon-sm spin") : "", text);
}
editToggle.addEventListener("click", () => setEditOpen(editForm.classList.contains("hidden")));
document.getElementById("edit-cancel").addEventListener("click", () => { setEditStatus(""); setEditOpen(false); });
editForm.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { e.preventDefault(); setEditOpen(false); }
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) editForm.requestSubmit();
});
editForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = editBox.value.trim();
  if (question.length < 10) { setEditStatus("Write a question of at least 10 characters.", true); editBox.focus(); return; }
  if (!editAccess.classList.contains("hidden") && editAccess.value.trim()) setAccessCode(editAccess.value.trim());
  const depth = editForm.querySelector("input[name=edit-depth]:checked").value;
  const button = document.getElementById("edit-submit");
  button.disabled = true;
  setEditStatus("Starting the new run…");
  try {
    const next = await api(`/api/runs/${runId}/rerun`, { method: "POST", headers: accessHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ question, depth, web_search: document.getElementById("edit-web")?.checked }) });
    window.location.href = `/runs/${next.run_id}`;
  } catch (err) {
    if (/access code/i.test(err.message)) { editAccess.classList.remove("hidden"); editAccess.focus(); }
    setEditStatus(`Could not start again: ${err.message}`, true);
    button.disabled = false;
  }
});

if (root.dataset.status === "done") setStatus("done", "Loading report…");
refreshTokens();
listenForProgress(); // replays the stored trail, then follows live events until the run ends
