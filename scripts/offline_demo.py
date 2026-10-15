"""Create a demo run WITHOUT keys or network, using the fake Mesh and fake search from tests/.

Useful to check the UI before your Mesh key is set up:
    python -m scripts.offline_demo
    python run.py            # then open the printed /runs/<id> page

Never use this for evaluation numbers: the data is synthetic.
"""

from __future__ import annotations

from dotenv import load_dotenv

from app.agents.researcher import agent as researcher_module
from app.db import repository as repo
from app.db.session import init_db
from app.llm import mesh_client
from app.services.run_service import execute_run
from tests.fakes import FakeMesh, fake_fetch, fake_search

QUESTION = "What are the main risks of investing in the EV battery market in 2026? (offline demo)"


def main() -> None:
    load_dotenv()
    init_db()
    mesh_client.set_mesh(FakeMesh())
    researcher_module.web_search = fake_search
    researcher_module.fetch_page = fake_fetch
    run_id = "run_offline_demo"
    if repo.get_run(run_id) is None:
        repo.create_run(run_id, QUESTION, "standard", [])
        execute_run(run_id, QUESTION, "standard", [])
    print(f"Demo run ready: http://127.0.0.1:8000/runs/{run_id}")


if __name__ == "__main__":
    main()
