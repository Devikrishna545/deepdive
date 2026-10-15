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

async function api(path, options = {}) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (_) { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return resp.json();
}

// Mesh credit banner: shown on every page when the balance is low, blocked or unreadable.
async function showBalanceBanner() {
  const banner = document.getElementById("balance-banner");
  if (!banner) return;
  try {
    const { balance } = await api("/api/health");
    if (balance.level === "ok") return;
    banner.className = `balance-banner balance-${balance.level}`;
    banner.replaceChildren(el("div", { class: "max-w-6xl mx-auto px-4 py-2 text-sm" }, balance.message));
  } catch (_) { /* health is best-effort */ }
}
document.addEventListener("DOMContentLoaded", showBalanceBanner);

function safeUrl(url) {
  try {
    const u = new URL(url);
    return ["http:", "https:"].includes(u.protocol) ? u.href : null;
  } catch (_) { return null; }
}
