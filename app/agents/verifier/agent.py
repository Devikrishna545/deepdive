"""Verifier agent: one claim vs. the text of the chunks it cites -> Verdict.

Isolation is the point: the verifier sees ONE claim and ONLY its cited chunk text,
never the draft, the question or other claims. It should run on a different model
family from the Drafter (MODEL_VERIFIER).

Per claim:
  1. precheck (code, no LLM): numbers in the claim missing from the source -> hint
  2. LLM judgement: SUPPORTED / PARTIAL / UNSUPPORTED / CONTRADICTED + exact quote
  3. quote guard (code): quote not literally in the source -> downgrade to UNSUPPORTED
  4. PARTIAL with a narrowed claim -> verify the narrowed child claim once
"""

from __future__ import annotations

from app.agents.base import chunk_block, load_prompt
from app.config import get_settings
from app.core.guards import apply_quote_guard, precheck_claim, verbatim_in_sources
from app.core.schemas import Chunk, Claim, Source, Verdict, VerdictLabel, VerdictOut
from app.core.utils import new_id
from app.llm.mesh_client import get_mesh


class VerifierAgent:
    name = "verifier"

    def _judge(self, claim: Claim, chunks: dict[str, Chunk], sources: dict[str, Source]) -> Verdict:
        s = get_settings()
        cited = [chunks[cid] for cid in claim.cited_chunk_ids if cid in chunks]
        texts = [c.text for c in cited]
        hints = precheck_claim(claim.text, texts)
        if not cited:
            return Verdict(
                claim_id=claim.id,
                label=VerdictLabel.UNSUPPORTED,
                reason="cited chunk does not exist",
                model="code",
                precheck_hints=hints,
            )
        # Free fast path: the claim is copied word for word from its source. No LLM needed.
        if verbatim_in_sources(claim.text, texts):
            return Verdict(
                claim_id=claim.id,
                label=VerdictLabel.SUPPORTED,
                reason="claim appears verbatim in the cited source",
                evidence_quote=claim.text.strip().rstrip("."),
                model="code:verbatim",
            )
        blocks = "\n\n".join(chunk_block(c.id, c.text) for c in cited)
        check = f"\nCHECK: {'; '.join(hints)}." if hints else ""  # code hints make the LLM stricter for ~10 tokens
        out = get_mesh().chat_json(
            model=s.model_verifier,
            system=load_prompt(self.name),
            user=f"CLAIM: {claim.text}{check}\n\nSOURCE:\n{blocks}",
            schema=VerdictOut,
            temperature=0.0,
            max_tokens=200,  # reply is a label, <=12-word reason and one short quote
        )
        verdict = Verdict(
            claim_id=claim.id,
            label=out.label,
            reason=out.reason,
            evidence_quote=out.evidence_quote,
            narrowed_claim=out.narrowed_claim,
            model=s.model_verifier,
            precheck_hints=hints,
        )
        return apply_quote_guard(verdict, texts)

    def verify(
        self, claim: Claim, chunks: dict[str, Chunk], sources: dict[str, Source]
    ) -> list[tuple[Claim, Verdict]]:
        """Return [(claim, verdict)] plus [(narrowed_child, child_verdict)] for PARTIAL claims."""
        verdict = self._judge(claim, chunks, sources)
        results = [(claim, verdict)]
        if verdict.label == VerdictLabel.PARTIAL and verdict.narrowed_claim:
            child = claim.model_copy(
                update={"id": new_id("clm"), "text": verdict.narrowed_claim.strip(), "parent_claim_id": claim.id}
            )
            results.append((child, self._judge(child, chunks, sources)))
        return results

    @staticmethod
    def passthrough(claim: Claim) -> Verdict:
        """Ablation mode (VERIFY_ENABLED=false): accept every claim unchecked."""
        return Verdict(claim_id=claim.id, label=VerdictLabel.SUPPORTED, reason="verification disabled", model="none")
