"""Day-1 check: can each configured model answer through Mesh, in JSON, and embed?

    python -m scripts.smoke_mesh

Prints one line per model. Fix model names in .env until every line says ok.
Cost: 6 tiny calls + 1 embedding, well under one cent. Check prices first, for free, with
`python -m scripts.mesh_account`.
"""

from __future__ import annotations

from dotenv import load_dotenv
from pydantic import BaseModel

from app.config import get_settings
from app.llm.mesh_client import get_mesh


class Ping(BaseModel):
    ok: bool
    model_family: str


def main() -> None:
    load_dotenv()
    s = get_settings()
    mesh = get_mesh()
    models = {
        "planner": s.model_planner, "researcher": s.model_researcher, "drafter": s.model_drafter,
        "verifier": s.model_verifier, "synthesizer": s.model_synthesizer, "judge": s.model_judge,
    }
    seen: set[str] = set()
    for role, model in models.items():
        if model in seen:  # one call per distinct model is enough
            print(f"{role:12} {model:40} ok   (same model as above)")
            continue
        seen.add(model)
        try:
            out = mesh.chat_json(model=model, system="You are a test.", user='Reply {"ok": true, "model_family": "<your family>"}', schema=Ping, max_tokens=60)
            print(f"{role:12} {model:40} ok   ({out.model_family})")
        except Exception as exc:
            print(f"{role:12} {model:40} FAIL {type(exc).__name__}: {exc}")
    try:
        vec = mesh.embed(["hello"])[0]
        print(f"{'embeddings':12} {s.embedding_model:40} ok   (dim {len(vec)})")
    except Exception as exc:
        print(f"{'embeddings':12} {s.embedding_model:40} FAIL {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
