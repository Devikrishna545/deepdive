---
title: DeepDive
emoji: 🔎
colorFrom: indigo
colorTo: pink
sdk: docker
app_port: 7860
pinned: false
short_description: Self-verifying multi-agent research analyst
---

# DeepDive: a self-verifying research analyst

Ask a research question (or attach your documents) and five agents plan, research, draft, verify
and write a report in which every sentence is checked against its source. Click any citation to
see the exact passage with the quoted words highlighted; the Claims tab shows what the verifier
removed, and the Audit trail shows every step.

All model calls go through Mesh API. Source code, design decisions and self-evaluation:
https://github.com/Devikrishna545/deepdive

This demo may ask for an access code to start new research (to protect the model credit); reading
reports is open. It sleeps when unused and wakes on the next visit (about a minute).
