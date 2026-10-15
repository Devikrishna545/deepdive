# app/agents — rules for every agent

Each agent has its own folder with three files. **Read the agent's `SKILL.md` before editing it.**

```
<agent>/agent.py    one class, explicit inputs -> outputs, no graph state access
<agent>/prompt.md   the system prompt (extra prompts as <name>_prompt.md)
<agent>/SKILL.md    contract, guardrails, failure modes, how to test
```

| Agent | Job | Model setting | Sees |
| --- | --- | --- | --- |
| planner | question -> sub-questions + queries; thin topic -> gap queries | MODEL_PLANNER | question, rejection reasons |
| researcher | sub-question -> sources, chunks, findings (chunk-cited) | MODEL_RESEARCHER | chunks it fetched |
| drafter | findings -> atomic cited claims | MODEL_DRAFTER | findings only (chunk ids, no chunk text) |
| verifier | ONE claim vs ITS cited chunks -> verdict | MODEL_VERIFIER (different family) | one claim + its chunks only |
| synthesizer | kept claims -> report sentences with claim ids | MODEL_SYNTHESIZER | kept claims only |

Shared rules:

1. Call models only via `get_mesh().chat_json(model=..., system=load_prompt(...), user=..., schema=...)`.
2. `load_prompt()` appends the prompt-injection guard. Never build a system prompt without it.
3. Wrap evidence in `chunk_block()` so the model can tell data from instructions.
4. Validate LLM output against real IDs: drop any chunk or claim ID the agent was not given.
5. Agents are distinct on purpose (judging criterion): own prompt, own schema, own tools.
   Do not merge two agents or share one prompt between them.
6. Agents never write to the DB or the graph state; nodes in `app/graph/nodes.py` do that.
7. Temperature 0 for planner, researcher, drafter, verifier (reproducible eval);
   synthesizer may use up to 0.3.
8. Every behaviour change needs a test using `tests/fakes.py::FakeMesh`.
9. Credits are scarce: pass `max_tokens` on every call, keep `prompt.md` short (~150 tokens),
   send only the inputs listed in the table above, and prefer a code check to an extra LLM call.
   Current caps: planner 500 / gap 150, researcher 800, drafter 700, verifier 200,
   synthesizer 1400, contradiction pairs 120.
