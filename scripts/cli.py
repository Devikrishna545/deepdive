"""Run one research question from the terminal (no web UI needed).

    python -m scripts.cli "What are the main risks of investing in the EV battery market in 2026?"

Prints the Markdown report and the run id; the audit trail is in the DB and the web UI.
"""

from __future__ import annotations

import argparse
import logging

from dotenv import load_dotenv

from app.core.utils import new_id
from app.db import repository as repo
from app.db.session import init_db
from app.services.run_service import execute_run


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--depth", choices=["quick", "standard"], default="quick")
    args = parser.parse_args()
    init_db()
    run_id = new_id("run")
    repo.create_run(run_id, args.question, args.depth, [])
    state = execute_run(run_id, args.question, args.depth, [])
    print(state["report"].markdown)
    print(f"\nrun id: {run_id}  (open http://127.0.0.1:8000/runs/{run_id} with `python run.py`)")


if __name__ == "__main__":
    main()
