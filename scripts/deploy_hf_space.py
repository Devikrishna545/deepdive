"""Publish DeepDive to a Hugging Face Space (Docker SDK).

    pip install huggingface_hub
    export HF_TOKEN=hf_...            # a token with write access (huggingface.co/settings/tokens)
    python scripts/deploy_hf_space.py --space <your-hf-username>/deepdive [--dry-run]

Uploads only files tracked by git (so .env, data/ and local caches can never be included), minus
what the Space does not need (CI, README screenshots). The Space's README is the Space card in
deploy/huggingface/README.md (Hugging Face reads its YAML header for the Docker settings).
Non-secret settings are set as Space variables. Secrets are NOT handled here: add MESH_API_KEY,
TAVILY_API_KEY and RUN_ACCESS_CODE yourself in the Space's Settings -> Variables and secrets.
Uses the Hugging Face API rather than git, so the PNG icons upload without git-lfs.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_PREFIXES = (".github/", "docs/screenshots/")
SPACE_VARIABLES = {
    "FRAME_ANCESTORS": "https://huggingface.co",  # the Space page shows the app in an iframe
    "MAX_RUNS_PER_DAY": "30",  # credit guard; change in the Space settings
    "DEV_MODE": "false",
}
SECRETS_TO_ADD = ("MESH_API_KEY", "TAVILY_API_KEY", "RUN_ACCESS_CODE")


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return [f for f in out.splitlines() if f and not f.startswith(SKIP_PREFIXES) and (ROOT / f).is_file()]


def stage(files: list[str], target: Path) -> None:
    for rel in files:
        if rel == "README.md":
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
    shutil.copy2(ROOT / "deploy" / "huggingface" / "README.md", target / "README.md")
    if any(n.startswith(".env") and n != ".env.example" for n in (p.name for p in target.rglob("*"))):
        raise SystemExit("refusing to upload: an .env file was staged")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--space", required=True, help="<hf-username>/<space-name>, e.g. devikrishna/deepdive")
    parser.add_argument("--dry-run", action="store_true", help="list what would be uploaded, upload nothing")
    args = parser.parse_args()

    files = tracked_files()
    with tempfile.TemporaryDirectory() as tmp:
        stage(files, Path(tmp))
        staged = sorted(str(p.relative_to(tmp)) for p in Path(tmp).rglob("*") if p.is_file())
        print(f"{len(staged)} files staged for {args.space}")
        if args.dry_run:
            print("\n".join(staged))
            return
        from huggingface_hub import HfApi  # deploy-only dependency

        api = HfApi()  # reads HF_TOKEN
        api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True)
        for key, value in SPACE_VARIABLES.items():
            api.add_space_variable(args.space, key, value)
        api.upload_folder(repo_id=args.space, repo_type="space", folder_path=tmp,
                          commit_message="Deploy DeepDive", delete_patterns=["*"])
    print(f"Uploaded. Space: https://huggingface.co/spaces/{args.space}")
    print("Next: in the Space's Settings -> Variables and secrets, add these as SECRETS:", ", ".join(SECRETS_TO_ADD))


if __name__ == "__main__":
    main()
