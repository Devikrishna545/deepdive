// New research form: upload optional documents, then start a run and open its page.

const form = document.getElementById("run-form");
const statusEl = document.getElementById("form-status");
const submitBtn = document.getElementById("submit");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = document.getElementById("question").value.trim();
  const depth = form.querySelector("input[name=depth]:checked").value;
  const files = document.getElementById("files").files;
  if (question.length < 10) {
    statusEl.textContent = "Write a question of at least 10 characters.";
    return;
  }
  submitBtn.disabled = true;
  try {
    const fileIds = [];
    for (const file of files) {
      statusEl.textContent = `Reading ${file.name}…`;
      const body = new FormData();
      body.append("file", file);
      const uploaded = await api("/api/files", { method: "POST", body });
      fileIds.push(uploaded.file_id);
    }
    statusEl.textContent = "Starting research…";
    const run = await api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, depth, file_ids: fileIds }),
    });
    window.location.href = `/runs/${run.run_id}`;
  } catch (err) {
    statusEl.textContent = `Could not start the run: ${err.message}`;
    submitBtn.disabled = false;
  }
});
