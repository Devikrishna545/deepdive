// Developer token view: input vs output tokens per agent (DEV_MODE only).
// Bars are scaled to the largest agent total in the same view; numbers sit beside every bar,
// so colour is never the only carrier (input = blue, output = orange, legend above).

const TOKEN_COLORS = { input: "#2a78d6", output: "#eb6834" };

function fmt(n) { return Number(n || 0).toLocaleString(); }
function usd(n) { return n ? `$${Number(n).toFixed(4)}` : "$0"; }

function tokenLegend() {
  const swatch = (color, label) => el("span", { class: "inline-flex items-center gap-1.5" },
    el("span", { class: "tok-swatch", style: `background:${color}` }), label);
  return el("div", { class: "flex gap-4 text-xs text-slate" },
    swatch(TOKEN_COLORS.input, "Input (prompt) tokens"),
    swatch(TOKEN_COLORS.output, "Output (completion) tokens"));
}

function tokenBar(input, output, max) {
  const pct = (v) => (max ? (v / max) * 100 : 0);
  const title = `${fmt(input)} in / ${fmt(output)} out`;
  return el("div", { class: "tok-bar", title, role: "img", "aria-label": title },
    input ? el("span", { class: "tok-seg", style: `width:${pct(input)}%;background:${TOKEN_COLORS.input}` }) : null,
    output ? el("span", { class: "tok-seg", style: `width:${pct(output)}%;background:${TOKEN_COLORS.output}` }) : null);
}

// rows: [{agent, calls, prompt_tokens, completion_tokens, cost_usd, models?}]
function agentTokenTable(rows, { showModels = true, caption = "" } = {}) {
  const max = Math.max(1, ...rows.map((r) => r.prompt_tokens + r.completion_tokens));
  const head = ["Agent", showModels ? "Model" : null, "Calls", "Input", "Output", "Total", "Cost", ""].filter((h) => h !== null);
  const totalIn = rows.reduce((s, r) => s + r.prompt_tokens, 0);
  const totalOut = rows.reduce((s, r) => s + r.completion_tokens, 0);
  const totalCost = rows.reduce((s, r) => s + (r.cost_usd || 0), 0);
  const totalCalls = rows.reduce((s, r) => s + (r.calls || 0), 0);
  return el("table", { class: "tok-table" },
    caption ? el("caption", {}, caption) : null,
    el("thead", {}, el("tr", {}, head.map((h, i) => el("th", { class: i >= (showModels ? 2 : 1) && i < head.length - 1 ? "num" : "" }, h)))),
    el("tbody", {}, rows.map((r) => el("tr", { class: r.calls ? "" : "tok-idle" },
      el("td", { class: "font-medium" }, r.agent),
      showModels ? el("td", { class: "text-slate whitespace-nowrap" }, (r.models || []).join(", ") || "-") : null,
      el("td", { class: "num" }, fmt(r.calls)),
      el("td", { class: "num" }, fmt(r.prompt_tokens)),
      el("td", { class: "num" }, fmt(r.completion_tokens)),
      el("td", { class: "num font-medium" }, fmt(r.prompt_tokens + r.completion_tokens)),
      el("td", { class: "num" }, usd(r.cost_usd)),
      el("td", { class: "tok-bar-cell" }, tokenBar(r.prompt_tokens, r.completion_tokens, max))))),
    el("tfoot", {}, el("tr", {},
      el("td", {}, "Total"), showModels ? el("td", {}) : null,
      el("td", { class: "num" }, fmt(totalCalls)),
      el("td", { class: "num" }, fmt(totalIn)),
      el("td", { class: "num" }, fmt(totalOut)),
      el("td", { class: "num" }, fmt(totalIn + totalOut)),
      el("td", { class: "num" }, usd(totalCost)),
      el("td", {}))));
}

function stepTokenTable(steps) {
  return el("details", { class: "mt-4" },
    el("summary", { class: "cursor-pointer text-sm text-slate" }, `Per step (${steps.length})`),
    el("table", { class: "tok-table mt-2" },
      el("thead", {}, el("tr", {}, ["Step", "Agent", "Calls", "Input", "Output", "Cost", "Time"].map((h, i) =>
        el("th", { class: i >= 2 ? "num" : "" }, h)))),
      el("tbody", {}, steps.map((s) => el("tr", {},
        el("td", {}, s.node),
        el("td", {}, s.agent),
        el("td", { class: "num" }, fmt(s.calls)),
        el("td", { class: "num" }, fmt(s.prompt_tokens)),
        el("td", { class: "num" }, fmt(s.completion_tokens)),
        el("td", { class: "num" }, usd(s.cost_usd)),
        el("td", { class: "num" }, `${(s.latency_ms / 1000).toFixed(1)} s`))))));
}

function renderRunTokens(container, data) {
  const biggest = [...data.agents].sort((a, b) => (b.prompt_tokens + b.completion_tokens) - (a.prompt_tokens + a.completion_tokens))[0];
  const share = data.totals.total_tokens && biggest ? Math.round(((biggest.prompt_tokens + biggest.completion_tokens) / data.totals.total_tokens) * 100) : 0;
  container.replaceChildren(
    data.totals.total_tokens
      ? el("p", { class: "text-sm" }, el("span", { class: "font-semibold" }, `${fmt(data.totals.total_tokens)} tokens`),
          ` (${fmt(data.totals.prompt_tokens)} in, ${fmt(data.totals.completion_tokens)} out) across ${fmt(data.totals.calls)} Mesh calls, ${usd(data.totals.cost_usd)}. `,
          biggest ? `${biggest.agent} used ${share}%.` : "")
      : el("p", { class: "text-sm text-slate" }, "No model calls recorded yet."),
    el("div", { class: "mt-3" }, tokenLegend()),
    el("div", { class: "mt-2 overflow-x-auto" }, agentTokenTable(data.agents)),
    data.steps.length ? stepTokenTable(data.steps) : null);
}
