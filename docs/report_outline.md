# Report outline

1. Introduction: problem, scope (one service area, simulated fleet, no link to real emergency services), objectives
2. Background: dispatch workflows, triage ideas (ESI, START), assignment problems, related systems (cite sources)
3. System design: architecture diagram, data model, which decisions are AI and which are deterministic,
   safety rules (human confirms, protocol floor, AI suggestions stored separately)
4. Implementation: PostGIS and OSRM, atomic assignment and locking, events and WebSockets,
   AI pipeline and fallback, optimizer, security
5. Evaluation method: datasets (synthetic, labelling rubric, agreement), metrics, baselines, simulation setup
6. Results: AI triage, dispatch optimizer (three settings), reliability, load, security (use docs/results.md)
7. Discussion: what the results support and what they do not (see caveats in results.md), limitations
8. Conclusion and future work: dynamic arrivals, real GPS feeds, mutual aid, multilingual evaluation at scale
Appendix: API list, schema, test scripts, rubric
