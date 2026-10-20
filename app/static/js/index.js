// New research: question composer with optional documents (button or drag and drop).

const form = document.getElementById("run-form");
const question = document.getElementById("question");
const fileInput = document.getElementById("files");
const chips = document.getElementById("file-chips");
const statusEl = document.getElementById("form-status");
const submitBtn = document.getElementById("submit");
const ACCEPT = [".pdf", ".docx", ".txt", ".md"];
const accessInput = document.getElementById("access-code");
let files = [];

function showAccessField() {
  accessInput.classList.remove("hidden");
  accessInput.value = getAccessCode();
}
api("/api/health").then((h) => { if (h.access_code_required) showAccessField(); }).catch(() => {});

function setStatus(text, { error = false, busy = false } = {}) {
  statusEl.className = `form-status${error ? " error" : ""}`;
  statusEl.replaceChildren(busy ? icon("loader-circle", "icon-sm spin") : error ? icon("circle-alert", "icon-sm") : "", text);
}

function autosize() {
  question.style.height = "auto";
  question.style.height = `${question.scrollHeight}px`;
}
question.addEventListener("input", autosize);
question.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) form.requestSubmit();
});

// With documents attached: optional web add-on (documents first, plus the web).
const webToggle = document.getElementById("web-toggle");
const webSearch = document.getElementById("web-search");
const webHint = document.getElementById("web-hint");
function updateWebToggle() {
  const on = files.length > 0;
  webToggle.classList.toggle("hidden", !on);
  webHint.classList.toggle("hidden", !on);
  webHint.textContent = webSearch.checked
    ? "Questions about your documents are answered from them first, plus what the web adds."
    : "Questions about your documents are answered from them only. Turn on web search to fill in what they don't cover.";
}
webSearch.addEventListener("change", updateWebToggle);

function renderChips() {
  chips.replaceChildren(...files.map((f, i) => el("span", { class: "file-chip" },
    icon("file-text", "icon-sm"), el("span", { title: f.name }, f.name),
    el("button", { type: "button", "aria-label": `Remove ${f.name}`, onclick: () => { files.splice(i, 1); renderChips(); } }, icon("x", "icon-sm")))));
  updateWebToggle();
}

function addFiles(list) {
  const skipped = [];
  for (const f of list) {
    if (ACCEPT.some((ext) => f.name.toLowerCase().endsWith(ext))) {
      if (!files.some((x) => x.name === f.name && x.size === f.size)) files.push(f);
    } else skipped.push(f.name);
  }
  renderChips();
  if (skipped.length) setStatus(`Skipped ${skipped.join(", ")}: only PDF, DOCX, TXT and MD files can be used.`, { error: true });
  else setStatus("");
}
fileInput.addEventListener("change", () => { addFiles(fileInput.files); fileInput.value = ""; });
document.getElementById("attach").addEventListener("click", () => fileInput.click());

// Drag and drop onto the composer.
let depth = 0;
form.addEventListener("dragenter", (e) => { if (e.dataTransfer?.types.includes("Files")) { e.preventDefault(); depth++; form.classList.add("dragging"); } });
form.addEventListener("dragover", (e) => { if (e.dataTransfer?.types.includes("Files")) e.preventDefault(); });
form.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) form.classList.remove("dragging"); });
form.addEventListener("drop", (e) => {
  e.preventDefault(); depth = 0; form.classList.remove("dragging");
  if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files);
});

document.querySelectorAll(".suggestion").forEach((b) => b.addEventListener("click", () => {
  question.value = b.textContent.trim(); autosize(); question.focus();
}));

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = question.value.trim();
  const depthValue = form.querySelector("input[name=depth]:checked").value;
  if (text.length < 10) {
    setStatus("Write a question of at least 10 characters.", { error: true });
    question.focus();
    return;
  }
  if (!accessInput.classList.contains("hidden")) setAccessCode(accessInput.value.trim());
  submitBtn.disabled = true;
  try {
    const fileIds = [];
    for (const file of files) {
      setStatus(`Reading ${file.name}…`, { busy: true });
      const body = new FormData();
      body.append("file", file);
      const uploaded = await api("/api/files", { method: "POST", body, headers: accessHeaders() });
      fileIds.push(uploaded.file_id);
    }
    setStatus("Starting research…", { busy: true });
    const run = await api("/api/runs", {
      method: "POST",
      headers: accessHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ question: text, depth: depthValue, file_ids: fileIds, web_search: webSearch.checked && fileIds.length > 0 }),
    });
    window.location.href = `/runs/${run.run_id}`;
  } catch (err) {
    if (/access code/i.test(err.message)) { showAccessField(); accessInput.focus(); }
    setStatus(`Could not start the research: ${err.message}`, { error: true });
    submitBtn.disabled = false;
  }
});

autosize();

// ------------------------------------------------------------------ manage the list: delete one, select several
const runList = document.getElementById("run-list");
if (runList) {
  const listStatus = document.getElementById("list-status");
  const selectToggle = document.getElementById("select-toggle");
  const selectBar = document.getElementById("select-bar");
  const selectAll = document.getElementById("select-all");
  const selectCount = document.getElementById("select-count");
  const deleteSelected = document.getElementById("delete-selected");
  const dialog = document.getElementById("confirm-delete");
  let pendingDelete = null; // ids waiting for the confirm dialog

  const checks = () => [...runList.querySelectorAll(".run-check")];
  const enabledChecks = () => checks().filter((c) => !c.disabled);
  const selectedIds = () => checks().filter((c) => c.checked).map((c) => c.value);

  function setListStatus(text, error = false) {
    listStatus.className = `form-status${error ? " error" : ""}`;
    listStatus.replaceChildren(text ? icon(error ? "circle-alert" : "check", "icon-sm") : "", text);
  }

  function updateSelection() {
    const n = selectedIds().length;
    const total = enabledChecks().length;
    selectCount.textContent = `${n} selected`;
    deleteSelected.disabled = n === 0;
    selectAll.checked = total > 0 && n === total;
    selectAll.indeterminate = n > 0 && n < total;
  }

  function setSelecting(on) {
    runList.classList.toggle("selecting", on);
    selectBar.classList.toggle("hidden", !on);
    runList.querySelectorAll(".row-check").forEach((l) => l.classList.toggle("hidden", !on));
    selectToggle.setAttribute("aria-pressed", String(on));
    selectToggle.querySelector("span").textContent = on ? "Done" : "Select";
    if (!on) checks().forEach((c) => { c.checked = false; });
    updateSelection();
  }

  selectToggle.addEventListener("click", () => setSelecting(selectToggle.getAttribute("aria-pressed") !== "true"));
  selectAll.addEventListener("change", () => { enabledChecks().forEach((c) => { c.checked = selectAll.checked; }); updateSelection(); });
  runList.addEventListener("change", (e) => { if (e.target.classList.contains("run-check")) updateSelection(); });

  function askToDelete(ids) {
    pendingDelete = ids;
    const one = ids.length === 1;
    const q = one ? runList.querySelector(`[data-run-id="${CSS.escape(ids[0])}"] .q`)?.textContent.trim() : "";
    document.getElementById("confirm-title").textContent = one ? "Delete this research?" : `Delete ${ids.length} research runs?`;
    document.getElementById("confirm-text").textContent = (one && q ? `“${q}” will be removed with its report, claims and audit trail.`
      : "Their reports, claims and audit trails are removed.") + " This can’t be undone.";
    dialog.showModal();
    document.getElementById("confirm-cancel").focus();
  }

  runList.addEventListener("click", (e) => {
    const btn = e.target.closest(".row-delete");
    if (btn && !btn.disabled) askToDelete([btn.closest(".run-row").dataset.runId]);
  });
  deleteSelected.addEventListener("click", () => { const ids = selectedIds(); if (ids.length) askToDelete(ids); });
  document.getElementById("confirm-cancel").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); }); // click outside closes
  dialog.addEventListener("close", () => { pendingDelete = null; });

  document.getElementById("confirm-ok").addEventListener("click", async () => {
    const ids = pendingDelete || [];
    dialog.close();
    if (!ids.length) return;
    if (!accessInput.classList.contains("hidden") && accessInput.value.trim()) setAccessCode(accessInput.value.trim());
    const rows = ids.map((id) => runList.querySelector(`[data-run-id="${CSS.escape(id)}"]`)).filter(Boolean);
    rows.forEach((r) => r.classList.add("removing"));
    try {
      const result = ids.length === 1
        ? await api(`/api/runs/${encodeURIComponent(ids[0])}`, { method: "DELETE", headers: accessHeaders() })
        : await api("/api/runs/delete", { method: "POST", headers: accessHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ run_ids: ids }) });
      const gone = new Set(result.deleted);
      rows.forEach((r) => (gone.has(r.dataset.runId) ? r.remove() : r.classList.remove("removing")));
      const skipped = (result.skipped || []).length;
      setListStatus(`Deleted ${gone.size} research run${gone.size === 1 ? "" : "s"}`
        + (skipped ? `; ${skipped} still running and kept.` : "."));
      if (!runList.children.length) {
        runList.remove(); selectBar.remove(); selectToggle.remove();
        document.getElementById("list-empty").classList.remove("hidden");
      } else if (selectToggle.getAttribute("aria-pressed") === "true") {
        updateSelection();
      }
    } catch (err) {
      rows.forEach((r) => r.classList.remove("removing"));
      if (/access code/i.test(err.message)) { showAccessField(); accessInput.focus(); }
      setListStatus(`Could not delete: ${err.message}`, true);
    }
  });
}
