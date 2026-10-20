# Deploying DeepDive

DeepDive is a FastAPI app served in a Docker container. Hugging Face's current Spaces
requirements say Docker and Gradio Spaces need a paid plan to create: PRO for personal accounts,
or Team/Enterprise for organizations. CPU Basic has no hourly hardware charge, but that does not
remove the plan requirement. Static Spaces are free, but cannot host this server-side app as-is.

When eligible, Hugging Face Spaces with the Docker SDK provides a public URL, Space-managed
secrets, and runs the same `Dockerfile` as other container hosts. CPU Basic provides 2 vCPU and
16 GB RAM. Its disk is not persistent, so local SQLite run history can be lost on restart.

If you do not want a Hugging Face paid plan, use another container host; see [Other hosts](#other-hosts)
and check the provider's current pricing and storage behavior.

## 1. Publish the Space

```bash
pip install huggingface_hub
export HF_TOKEN=hf_...                  # huggingface.co/settings/tokens, "Write" access
python scripts/deploy_hf_space.py --space OWNER/deepdive --dry-run   # see what goes up
python scripts/deploy_hf_space.py --space OWNER/deepdive
```

Replace `OWNER` with your Hugging Face username or organization name; do not include angle
brackets. For a personal account, make sure its PRO plan is active before creating the Space.

The script uploads only files tracked by git (never `.env` or `data/`), uses
`deploy/huggingface/README.md` as the Space card, and sets these Space **variables**:
`FRAME_ANCESTORS=https://huggingface.co` (the Space page shows the app in an iframe),
`MAX_RUNS_PER_DAY=30`, `DEV_MODE=false`.

## 2. Add the secrets (in the browser)

Space -> **Settings -> Variables and secrets -> New secret**:

| Secret | Value |
| --- | --- |
| `MESH_API_KEY` | your Mesh key |
| `TAVILY_API_KEY` | your Tavily key (DuckDuckGo is often blocked from cloud IPs) |
| `RUN_ACCESS_CODE` | a code you give the judges, e.g. `arena-2026` |

Saving a secret restarts the Space. The build takes a few minutes the first time.

## 3. Check it

1. Open `https://huggingface.co/spaces/<user>/deepdive`. The app loads inside the page.
2. `https://<user>-deepdive.hf.space/api/health` shows `"access_code_required": true`,
   `"mesh_key_configured": true` and the balance level (never the key).
3. Run one quick question with the access code; open a citation; check the Claims tab.
4. Attach a PDF and ask "what is this paper about?" (document mode).

## Credit safety

- `RUN_ACCESS_CODE`: only people with the code start research; reading reports stays open.
- `MAX_RUNS_PER_DAY`: hard cap across all visitors (each run is about $0.02-0.04).
- `RUN_BUDGET_USD` (0.15) and `MIN_BALANCE_STOP_USD` (1.0) still apply per run and per account.
- To stop all spending at once: pause the Space (Settings -> Pause) or remove `MESH_API_KEY`.

## Other hosts

The `Dockerfile` runs anywhere that sets `PORT` (Render, Fly.io, Railway, Cloud Run). Set the same
environment variables; leave `FRAME_ANCESTORS` empty unless the host shows the app in a frame.
