"""Drafter agent: findings for one sub-question -> atomic, cited claims.

One fact per claim, each citing at least one chunk ID that its finding came from. Claim
IDs are assigned by code. Citations to chunks that were not provided are stripped; a claim
left with no citation is discarded before verification.

Token note: the drafter sees the findings only, not the chunk texts. Findings are already
close to the source wording, and every claim is checked against the full chunk text by the
verifier afterwards, so re-sending the chunks here would roughly double the input cost for
no accuracy gain.
"""

from __future__ import annotations

from app.agents.base import load_prompt
from app.config import get_settings
from app.core.schemas import Chunk, Claim, ClaimsOut, Finding, SubQuestion
from app.core.utils import new_id
from app.llm.mesh_client import get_mesh


class DrafterAgent:
    name = "drafter"

    def draft(self, sq: SubQuestion, findings: list[Finding], chunks: dict[str, Chunk], round_no: int) -> list[Claim]:
        if not findings:
            return []
        cited = {cid for f in findings for cid in f.chunk_ids if cid in chunks}
        finding_lines = "\n".join(f"- {f.text} (chunks: {', '.join(f.chunk_ids)})" for f in findings)
        out = get_mesh().chat_json(
            model=get_settings().model_drafter,
            system=load_prompt(self.name),
            user=f"SUB-QUESTION: {sq.text}\n\nFINDINGS:\n{finding_lines}",
            schema=ClaimsOut,
            temperature=0.0,
            max_tokens=700,
        )
        claims: list[Claim] = []
        for c in out.claims:
            ids = [cid for cid in c.cited_chunk_ids if cid in cited]
            if ids and c.text.strip():
                claims.append(
                    Claim(
                        id=new_id("clm"),
                        sub_question_id=sq.id,
                        text=c.text.strip(),
                        cited_chunk_ids=ids,
                        claim_type=c.claim_type,
                        round=round_no,
                    )
                )
        return claims
