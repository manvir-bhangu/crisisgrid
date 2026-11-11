# Weekly log (edit in your own words; add one entry per week)

## Week 1 (1-10 Nov 2026)
- Chose CrisisGrid: AI-assisted emergency coordination for one service area in Amritsar.
- Built: Docker (PostGIS, Redis, OSRM), Amritsar OSM extract, facilities (OSM + manually added fire stations),
  simulated fleet (27 units), FastAPI API, atomic assignment with row locking and a state machine, audit log,
  WebSocket live feed, dispatcher dashboard, vehicle movement simulator, citizen and responder pages.
- AI: LLM triage with rule-based fallback, protocol severity floor, schema validation, response cache,
  duplicate-report heuristic. Pilot evaluation on 30 scenarios.
- Optimizer: Hungarian assignment with priority weights, compared with four baselines on 200 simulated surges.
- Reliability: Redis, OSRM and database outage checks; load tests; fixed a connection-holding bottleneck.
- Security: roles, hashed passwords, signed sessions, rate-limited public reports, automated access tests.
- Problems met and fixed: venv in the wrong folder, git repo in the wrong folder, wrong model name,
  malformed .env, rate limits, bottleneck found by load test.

## Week 2 (11-17 Nov 2026)
- Planned: 150-scenario dataset with independent labels, ablation, weighted-cost metric, report drafting.

## Open items
- Phone GPS demo, browser login walkthrough, dataset agreement, report, demo video, viva practice.
