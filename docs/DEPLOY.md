# Deploying DeepDive (free tier)

Recommended: **Hugging Face Spaces, Docker SDK, free CPU** (2 vCPU, 16 GB RAM). It gives a stable
public URL, keeps secrets in the Space settings, and runs the same `Dockerfile` as any other host.

| | Hugging Face Spaces (free) | Render (free) |
| --- | --- | --- |
| RAM | 16 GB | 512 MB |
| Sleeps after | 48 h without visits (wakes in ~1 min) | 15 min (slow first load) |
| Disk | resets on restart (run history is lost) | resets on restart |
| Secrets | Space settings | dashboard env vars |

Both free tiers lose the SQLite file on restart: judges see their own runs, not a history.

## Known limitation on free hosting: research history does not persist

DeepDive keeps everything in files under `data/`: the SQLite database (runs, claims, audit trail,
follow-up threads) and the uploaded documents. Free plans give the container a **temporary disk**.
It is wiped whenever the service restarts, redeploys, or wakes from sleep (Render free sleeps after
15 minutes without visits). What a visitor sees:

- The "Recent research" list on the home page is empty again after a restart.
- An old report link (`/runs/<id>`) shows the "not found" page.
- A run that was in progress when the service restarted is lost.
- Documents attached to earlier runs are gone, so Edit & run again and Continue this research
  cannot reuse them (attach them again).
- Reports finished in the current session work normally, including citations, the Claims tab,
  the audit trail, follow-ups and export. Save a report you want to keep with the Export button.

The app does not need changing to fix this. On a paid plan, attach a persistent disk and point
the two paths at it. Render: a paid instance type (Starter or above) plus a disk mounted at
`/var/data` (Disks, add disk), then set these environment variables:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | `sqlite:////var/data/deepdive.db` (four slashes: an absolute path) |
| `UPLOAD_DIR` | `/var/data/uploads` |

History, threads and attached documents then survive restarts and redeploys. A disk is tied to a
single instance, so keep one instance (SQLite is not meant for several). Check current prices on
the host's pricing page. For a large public deployment, move `DATABASE_URL` to a managed
Postgres database instead; the code uses SQLModel, but only SQLite has been tested.

## 1. Publish the Space (about 5 minutes)

```bash
pip install huggingface_hub
export HF_TOKEN=hf_...                  # huggingface.co/settings/tokens, "Write" access
python scripts/deploy_hf_space.py --space <your-hf-username>/deepdive --dry-run   # see what goes up
python scripts/deploy_hf_space.py --space <your-hf-username>/deepdive
```

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
