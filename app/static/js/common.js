// Shared helpers. All text from the API (which includes web content) is inserted with
// textContent via el(), never innerHTML, so fetched pages cannot inject markup.

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

// Lucide icon from the local sprite. Decorative (aria-hidden) unless a label is given.
function icon(name, cls = "", label = null) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", `icon ${cls}`.trim());
  svg.setAttribute("focusable", "false");
  if (label) { svg.setAttribute("role", "img"); svg.setAttribute("aria-label", label); }
  else svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(ns, "use");
  use.setAttribute("href", `${window.ICON_SPRITE || "/static/icons/sprite.svg"}#i-${name}`);
  svg.append(use);
  return svg;
}

async function api(path, options = {}) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (_) { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return resp.json();
}

// Access code for hosted demos (only asked for when the server requires one). Remembered in this
// browser when storage is allowed; sent with requests that start research or upload files.
const ACCESS_KEY = "deepdive-access-code";
function getAccessCode() {
  try { return localStorage.getItem(ACCESS_KEY) || ""; } catch (_) { return window.__accessCode || ""; }
}
function setAccessCode(code) {
  window.__accessCode = code;
  try { if (code) localStorage.setItem(ACCESS_KEY, code); else localStorage.removeItem(ACCESS_KEY); } catch (_) { /* storage blocked */ }
}
function accessHeaders(extra = {}) {
  const code = getAccessCode();
  return code ? { ...extra, "X-Access-Code": code } : extra;
}

function safeUrl(url) {
  try {
    const u = new URL(url);
    return ["http:", "https:"].includes(u.protocol) ? u.href : null;
  } catch (_) { return null; }
}

// "3 min ago", "yesterday", "12 Oct" for <time data-relative datetime="...">.
function relativeTime(iso) {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const s = Math.round((Date.now() - then.getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 172800) return "yesterday";
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
function applyRelativeTimes(root = document) {
  root.querySelectorAll("time[data-relative]").forEach((t) => {
    const text = relativeTime(t.getAttribute("datetime"));
    if (text) { t.textContent = text; t.title = new Date(t.getAttribute("datetime")).toLocaleString(); }
  });
}

// Theme: follows the system until the person picks one; the choice is remembered when storage works.
function setupThemeToggle() {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const root = document.documentElement;
    const current = root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (_) { /* storage blocked: still switches for this page */ }
  });
}

// Mesh credit banner: shown on every page when the balance is low, blocked or unreadable.
async function showBalanceBanner() {
  const banner = document.getElementById("balance-banner");
  if (!banner) return;
  try {
    const { balance } = await api("/api/health");
    if (balance.level === "ok") return;
    banner.className = `balance-banner balance-${balance.level}`;
    banner.replaceChildren(el("div", {}, icon(balance.level === "stop" ? "circle-x" : "triangle-alert"), balance.message));
  } catch (_) { /* health is best-effort */ }
}

// Installable app: the service worker caches the app shell only, never research data.
function registerServiceWorker() {
  if (!("serviceWorker" in navigator) || location.protocol === "file:") return;
  navigator.serviceWorker.register("/sw.js").catch(() => { /* optional */ });
}

document.addEventListener("DOMContentLoaded", () => {
  setupThemeToggle();
  applyRelativeTimes();
  showBalanceBanner();
  registerServiceWorker();
});
