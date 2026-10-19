// New research: question composer with optional documents (button or drag and drop).

const form = document.getElementById("run-form");
const question = document.getElementById("question");
const fileInput = document.getElementById("files");
const chips = document.getElementById("file-chips");
const statusEl = document.getElementById("form-status");
const submitBtn = document.getElementById("submit");
const ACCEPT = [".pdf", ".docx", ".txt", ".md"];
let files = [];

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

function renderChips() {
  chips.replaceChildren(...files.map((f, i) => el("span", { class: "file-chip" },
    icon("file-text", "icon-sm"), el("span", { title: f.name }, f.name),
    el("button", { type: "button", "aria-label": `Remove ${f.name}`, onclick: () => { files.splice(i, 1); renderChips(); } }, icon("x", "icon-sm")))));
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
document.getElementById("attach").addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
});

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
  submitBtn.disabled = true;
  try {
    const fileIds = [];
    for (const file of files) {
      setStatus(`Reading ${file.name}…`, { busy: true });
      const body = new FormData();
      body.append("file", file);
      const uploaded = await api("/api/files", { method: "POST", body });
      fileIds.push(uploaded.file_id);
    }
    setStatus("Starting research…", { busy: true });
    const run = await api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: text, depth: depthValue, file_ids: fileIds }),
    });
    window.location.href = `/runs/${run.run_id}`;
  } catch (err) {
    setStatus(`Could not start the research: ${err.message}`, { error: true });
    submitBtn.disabled = false;
  }
});

autosize();
