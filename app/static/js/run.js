// Run page: live progress over SSE, then the report, the claims and the audit trail.

const root = document.getElementById("run-root");
const runId = root.dataset.runId;
const state = { report: null, claims: null, claimById: {}, refBySource: {}, filter: "all" };

// ------------------------------------------------------------------ tabs
document.querySelectorAll("[role=tab]").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("[role=tab]").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
    document.getElementById(`panel-${tab.dataset.tab}`).classList.remove("hidden");
  });
});

// ------------------------------------------------------------------ pipeline progress
const pipeline = document.getElementById("pipeline");

function stepFor(node) {
  return pipeline.querySelector(`[data-node="${node.split(":")[0]}"]`);
}

function setNote(li, text) {
  let note = li.querySelector(".note");
  if (!note) { note = el("span", { class: "note" }); li.append(note); }
  note.textContent = text;
}

// ------------------------------------------------------------------ dev token view
const devMode = root.dataset.dev === "true";
let tokenTimer = null;

async function refreshTokens() {
  if (!devMode) return;
  try {
    renderRunTokens(document.getElementById("tokens"), await api(`/api/runs/${runId}/usage`));
  } catch (_) { /* dev view is best-effort */ }
}

function scheduleTokenRefresh() {
  if (!devMode || tokenTimer) return;
  tokenTimer = setTimeout(() => { tokenTimer = null; refreshTokens(); }, 1200); // batch bursts of events
}

function onTrailEvent(ev) {
  appendTrail(ev);
  if (ev.tokens) scheduleTokenRefresh();
  const li = stepFor(ev.node);
  if (!li) return;
  if (ev.phase === "start") {
    pipeline.querySelectorAll("li.active").forEach((x) => x !== li && x.classList.replace("active", "done"));
    li.classList.add("active");
  } else if (ev.phase === "end") {
    if (!ev.node.startsWith("research")) li.classList.replace("active", "done") || li.classList.add("done");
    setNote(li, ev.summary);
  } else if (ev.phase === "error") {
    li.classList.add("failed");
    setNote(li, ev.summary);
  }
}

function listenForProgress() {
  const source = new EventSource(`/api/runs/${runId}/events`);
  source.addEventListener("trail", (e) => onTrailEvent(JSON.parse(e.data)));
  source.addEventListener("done", (e) => {
    source.close();
    const info = JSON.parse(e.data);
    pipeline.querySelectorAll("li.active").forEach((x) => x.classList.replace("active", "done"));
    document.getElementById("run-status").textContent = info.status;
    refreshTokens();
    if (info.status === "done") loadResults();
    else document.getElementById("report-waiting").textContent = `The run failed: ${info.error || "see the audit trail"}.`;
  });
  source.onerror = () => { /* the browser reconnects automatically */ };
}

// ------------------------------------------------------------------ audit trail
const trailEl = document.getElementById("trail");

function appendTrail(ev) {
  if (ev.phase === "start") return; // keep the trail readable: finished steps only
  const meta = [ev.tokens ? `${ev.prompt_tokens ?? "?"} in / ${ev.completion_tokens ?? "?"} out tokens` : null, ev.cost_usd ? `$${ev.cost_usd.toFixed(4)}` : null, ev.latency_ms ? `${(ev.latency_ms / 1000).toFixed(1)} s` : null, ev.models || null]
    .filter(Boolean).join(", ");
  const hasPayload = ev.payload && Object.keys(ev.payload).length > 0;
  trailEl.append(
    el("li", { class: "bg-white border border-rule rounded-md px-3 py-2" },
      el("div", { class: "flex flex-wrap gap-x-3" },
        el("span", { class: `font-medium ${ev.phase === "error" ? "text-rejected" : ""}` }, ev.node),
        el("span", { class: "flex-1" }, ev.summary),
        el("span", { class: "text-slate" }, meta)),
      hasPayload ? el("details", { class: "mt-1" },
        el("summary", { class: "cursor-pointer text-slate" }, "Details"),
        el("pre", { class: "mt-2 text-xs overflow-x-auto whitespace-pre-wrap" }, JSON.stringify(ev.payload, null, 2))) : null));
}

// ------------------------------------------------------------------ report
function citeMarks(sentence) {
  const marks = [];
  for (const cid of sentence.claim_ids) {
    const claim = state.claimById[cid];
    if (!claim) continue;
    const nums = [...new Set(claim.chunks.map((c) => state.refBySource[c.source_id]).filter(Boolean))].sort((a, b) => a - b);
    const narrowed = Boolean(claim.parent_claim_id);
    marks.push(el("button", {
      class: `cite ${narrowed ? "narrowed" : "verified"}`,
      title: narrowed ? "Verified after narrowing to what the source says" : "Verified against the cited source",
      onclick: () => openSource(claim),
    }, nums.length ? nums.join(",") : "src"));
  }
  return marks;
}

function sentenceNode(sentence) {
  return el("span", {}, sentence.text, ...citeMarks(sentence), " ");
}

function renderReport() {
  const r = state.report;
  const article = document.getElementById("report");
  article.replaceChildren();
  article.append(el("h2", {}, "Summary"), el("div", { class: "summary" }, r.executive_summary.map((s) => el("p", {}, sentenceNode(s)))));
  for (const section of r.sections) {
    article.append(el("h2", {}, section.heading));
    if (section.limited_evidence) article.append(el("p", { class: "limited" }, "Limited evidence: this part did not reach two verified claims from two independent sources."));
    article.append(section.sentences.length
      ? el("p", {}, section.sentences.map(sentenceNode))
      : el("p", { class: "text-slate" }, "No claims survived verification for this part."));
  }
  if (r.disagreements.length) {
    article.append(el("h2", {}, "Where sources disagree"));
    article.append(el("ul", { class: "list-disc pl-5" }, r.disagreements.map((d) => el("li", {}, d.superseded_claim ? `${d.explanation} (the non-official claim was removed: an official source contradicts it)` : d.explanation))));
  }
  if (r.limitations.length) {
    article.append(el("h2", {}, "Limitations"));
    article.append(el("ul", { class: "list-disc pl-5" }, r.limitations.map((t) => el("li", {}, t))));
  }
  article.append(el("h2", {}, "References"));
  article.append(el("ol", { class: "refs list-decimal pl-5" }, r.references.map((ref) => {
    const href = safeUrl(ref.url);
    return el("li", {},
      href ? el("a", { href, target: "_blank", rel: "noopener noreferrer", class: "text-primary hover:underline" }, ref.title) : ref.title,
      ` (${ref.domain}${ref.page ? `, p.${ref.page}` : ""}, source quality ${ref.quality_score})`);
  })));
  document.getElementById("report-waiting").classList.add("hidden");
  article.classList.remove("hidden");
}

// ------------------------------------------------------------------ source dialog
const dialog = document.getElementById("source-dialog");
document.getElementById("dlg-close").addEventListener("click", () => dialog.close());

function openSource(claim) {
  const v = claim.verdict || {};
  document.getElementById("dlg-title").textContent = "Why this sentence is in the report";
  const body = document.getElementById("dlg-body");
  body.replaceChildren(
    el("p", {}, el("span", { class: `label label-${v.label}` }, v.label || "unchecked"), " ", claim.text),
    v.reason ? el("p", { class: "text-slate" }, v.reason) : null,
    v.evidence_quote ? el("blockquote", { class: "evidence" }, `“${v.evidence_quote}”`) : null,
    ...claim.chunks.map((chunk) => {
      const href = chunk.source ? safeUrl(chunk.source.url) : null;
      return el("div", { class: "border-t border-rule pt-3" },
        el("p", { class: "font-medium" },
          href ? el("a", { href, target: "_blank", rel: "noopener noreferrer", class: "text-primary hover:underline" }, chunk.source.title)
               : (chunk.source ? chunk.source.title : chunk.source_id),
          chunk.page ? ` (p.${chunk.page})` : ""),
        el("p", { class: "mt-1 text-slate whitespace-pre-wrap" }, chunk.text));
    }));
  dialog.showModal();
}

// ------------------------------------------------------------------ claims table
function renderClaims() {
  const wrap = document.getElementById("claims");
  wrap.replaceChildren();
  const visible = state.claims.claims.filter((c) =>
    state.filter === "all" || (state.filter === "kept" ? c.kept : !c.kept));
  for (const sq of state.claims.sub_questions) {
    const rows = visible.filter((c) => c.sub_question_id === sq.id);
    if (!rows.length) continue;
    wrap.append(el("h3", { class: "font-semibold mt-6 mb-2" }, sq.text));
    wrap.append(el("ul", { class: "space-y-2" }, rows.map((c) => {
      const v = c.verdict || {};
      return el("li", { class: "bg-white border border-rule rounded-md p-3 text-sm" },
        el("div", { class: "flex gap-2 items-start" },
          el("span", { class: `label label-${v.label}` }, v.label || "—"),
          el("span", { class: "flex-1" }, c.text),
          el("button", { class: "text-primary hover:underline", onclick: () => openSource(c) }, "Source")),
        v.reason ? el("p", { class: "mt-1 text-slate" }, c.parent_claim_id ? `Narrowed claim. ${v.reason}` : v.reason) : null);
    })));
  }
  if (!wrap.children.length) wrap.append(el("p", { class: "text-slate" }, "No claims match this filter."));
}

document.querySelectorAll("[data-filter]").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.filter = btn.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    renderClaims();
  });
});

// ------------------------------------------------------------------ stats + load
function renderStats() {
  const all = state.claims.claims;
  const kept = all.filter((c) => c.kept).length;
  const removed = all.filter((c) => !c.kept).length;
  const stats = document.getElementById("stats");
  stats.replaceChildren(
    el("p", {}, el("span", { class: "font-semibold" }, String(kept)), " claims kept"),
    el("p", {}, el("span", { class: "font-semibold text-rejected" }, String(removed)), " claims removed by the verifier"),
    el("p", {}, el("span", { class: "font-semibold" }, String(state.report.dropped_sentences.length)), " uncited sentences removed"),
    el("p", {}, el("span", { class: "font-semibold" }, String(state.report.references.length)), " sources cited"));
  stats.classList.remove("hidden");
}

async function loadResults() {
  try {
    const [report, claims, run] = await Promise.all([
      api(`/api/runs/${runId}/report`), api(`/api/runs/${runId}/claims`), api(`/api/runs/${runId}`)]);
    state.report = report;
    state.claims = claims;
    state.claimById = Object.fromEntries(claims.claims.map((c) => [c.id, c]));
    state.refBySource = Object.fromEntries(report.references.map((r) => [r.source_id, r.number]));
    document.getElementById("run-tokens").textContent =
      (run.tokens ? `, ${run.tokens.toLocaleString()} tokens` : "") + (run.cost_usd ? `, $${run.cost_usd.toFixed(4)} Mesh credit` : "");
    renderReport();
    renderClaims();
    renderStats();
    document.getElementById("export-md").classList.remove("hidden");
    document.getElementById("export-html").classList.remove("hidden");
  } catch (err) {
    document.getElementById("report-waiting").textContent = `Could not load the report: ${err.message}`;
  }
}

refreshTokens();
listenForProgress(); // replays the stored trail, then follows live events until the run ends
