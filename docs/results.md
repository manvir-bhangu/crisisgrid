# CrisisGrid - results log

All numbers are from one laptop (Windows, Docker for PostGIS/Redis/OSRM, one uvicorn process).
Scenarios and severity mixes are synthetic and written by the author.

## 1. AI triage pilot (30 synthetic scenarios, run_20261108_115026)

| Metric | B: rules only | C: LLM + protocol floor |
|---|---|---|
| Category accuracy | 66.7% | 96.7% |
| Category macro-F1 | 0.658 | 0.960 |
| Severity exact | 43.3% | 80.0% |
| Under-triage rate | 46.7% | 6.7% |
| Critical cases missed | 6/13 | 0/13 |
| McNemar (category) | | only B right 1, only C right 10, p = 0.012 |

Model: gemini-3.5-flash-lite, 0/30 fallbacks. Per-language rows (hi n=1, pa n=2) are too small to quote.
Caveats: labels, rules and prompt were all written by the author and an AI assistant. The keyword floor
contributes to the critical-case result; an ablation (LLM alone vs LLM + floor) is still to do.
C also over-triaged 4 of 30 reports.

## 2. Dispatch optimizer (12 ambulances, 200 trials per surge size, seed 42, road times from OSRM)

Methods: A nearest straight-line | B nearest road time | C road time + critical first |
D Hungarian unweighted | E Hungarian priority-weighted.

| Setting | Critical served, C and E | E vs C, critical response (N=8/15/25) | E vs C, mean over served (N=8/15/25) |
|---|---|---|---|
| Default: weights 8,4,2,1, 70% of units free | 100% / 100% / 99.6% | +1.3 / -1.7 / -4.3 s | -16 / -35 / -40 s |
| Flatter weights 4,3,2,1 | 100% / 100% / 99.6% | +7.4 / +4.7 / +2.1 s | -17 / -37 / -42 s |
| Scarce fleet: 50% of units free | 98.4% / 98.8% / 93.7% | +1.9 / -2.8 / -11.0 s | -22 / -37 / -45 s |

Findings:
- Serving critical incidents first (C and E) protects them: A and B served only 53% / 35% of critical
  incidents at N = 15 / 25 with 70% of units free.
- Hungarian adds a 16-45 s efficiency gain over critical-first in all nine settings, at the same critical coverage.
- Hungarian does NOT generally speed up critical cases. With flatter weights it is 2-7 s slower for them.
  It helps critical response clearly only when units are scarce (11 s faster at N = 25, 50% free).
- With a scarce fleet, 6% of critical incidents stay unserved at N = 25 whatever the algorithm.
- Straight-line vs road-time ranking (A vs B) differs by only about 4 s: a compact city makes them similar.
Caveats: D has the lowest mean only because it ignores severity (26-36% of critical served at N = 25).
About 18 paired tests per run, p-values uncorrected, differences of 2-7 s are operationally small.
Assumptions: uniform random incident locations, severity mix 15/25/35/25, one batch per surge,
driving time only, ambulances only, units start at stations.
Correctness: the Hungarian implementation matches exhaustive search on 200 random cases (pytest, 3 passed).

## 3. Reliability checks

| Condition | Result |
|---|---|
| Normal | Incident created (201), road ETAs, AI source = llm |
| Redis stopped, before fix | create 831-1293 ms, 201 |
| Redis stopped, after non-blocking publish | create 56-74 ms, 201, AI llm |
| OSRM stopped | recommendations ok, source = straight_line_fallback (1043 ms) |
| Database stopped | HTTP 500, nothing saved |
| 20 simultaneous requests for one ambulance | 1 x 201, 19 x 409 (PASS) |

## 4. Load test (300 incidents per run; AI setting during runs: TODO confirm)

| Clients | Create p50 / p95 / p99 (ms) | Throughput | Event delay p50 / p95 (ms) | Recommendations p50 / p95 (ms), 200 requests |
|---|---|---|---|---|
| 10 | 126 / 494 / 848 | 61.9 req/s | 27 / 45 | 71 / 127 |
| 20 | 154 / 214 / 227 | 122.3 req/s | 41 / 64 | 94 / 116 |
| 50 | 426 / 477 / 485 | 114.1 req/s | 23 / 36 | 320 / 347 |

Before the fix, recommendations at 50 clients succeeded 95/200 (ConnectError on 105, p50 5.7 s).
Three changes were made together (release DB connection before the OSRM call, shared HTTP client with a
20 s skip after a failure, larger connection pool), so the improvement is not attributed to one of them.
Write throughput levels off near 115-120 req/s on this machine.

## 5. Security

check_auth.py: all checks PASS (anonymous reads and writes refused, forged cookie and wrong key refused,
anonymous WebSocket refused, citizen cannot set a verified category, 10 simultaneous retries with one key give
one incident, anonymous reports rate limited).

## 6. Not yet demonstrated
- Phone GPS through the tunnel (unconfirmed)
- Browser login walkthrough
- 150-scenario dataset, independent labels and agreement
- LLM-only vs LLM + floor ablation

## 2b. Neutral weighted-cost check (equal scoring weights, 1800 s penalty per unserved incident)

Negative = E better. E optimises weights 8,4,2,1 in all rows.

| Setting | E vs C (N=8/15/25) | E vs D (N=8/15/25) |
|---|---|---|
| 70% of units free | -14.2 / -19.4 / -13.4 s | +12.2 / +31.9 / +30.3 s |
| 50% of units free | -15.6 / -14.6 / -10.5 s | +22.8 / +30.1 / +23.6 s |

With scoring weights equal to E's own (8,4,2,1, 70% free), E beats C by 9.1 / 16.5 / 16.1 s, but this is partly
by construction because E optimises that metric.

Reading: E matches critical-first on critical coverage and is about 10-19 s better than it on neutral cost.
Unweighted Hungarian (D) is 12-32 s better than E on neutral cost but serves far fewer critical incidents
(55.5% vs 100% at N = 15, 70% free). E is a trade-off, not a dominant method.
All methods serve the same number of incidents (limited by free units), so the unserved penalty is identical
across methods; differences come only from travel times of served incidents.

## Label provenance (state this in the report)
- All scenario texts and labels were written by the author with an AI assistant. No independent human annotator.
- Labels follow docs/rubric.md, adapted from the idea behind ESI and START triage (verify and cite properly).
- Consequence: results are a development benchmark on synthetic data. They show the pipeline works and how it
  behaves; they do not validate it against real dispatchers or real emergencies.
- Scenarios S001-S010 and S031-S060 are dev; S011-S030 are test. Rules and prompts were not tuned on test.
- Ambiguous labels (the assistant was unsure): S032, S045, S046, S049, S060.

## Batch 3 (S061-S090, test split)
- Written and labelled by the author with an AI assistant; no independent annotator.
- Deliberately includes keyword traps (fire station booking, burnt toast, fire alarm, "no fire"),
  emergencies without obvious keywords (blue lips, weak hand, neighbour not answering), and two injection attempts.
- Ambiguous labels (the assistant was unsure): S066, S069, S070, S073, S079, S082, S083.
- Test split is now S011-S030 and S061-S090 (50 scenarios). Do not tune rules or prompts after seeing test results.

## Batches 4 and 5 (S091-S150)
- Written and labelled by the author with an AI assistant; no independent annotator.
- Split: S091-S100 dev; S101-S150 test. Totals: 50 dev, 100 test.
- Ambiguous labels (the assistant was unsure): S097, S106, S111, S120, S124, S131, S139.
- Important limitation: the scenario author and labeller is itself a language model, and the system under
  test uses a language model. Shared blind spots can make agreement look better than it would be against
  human dispatchers. Treat all results as a development benchmark on synthetic data.
- Scenarios were not written to fit the rules or the prompt, but the author could see how both were built.

## 7. AI triage, 100 test scenarios (run_20261111_093841; model gemini-3.5-flash-lite, 0/100 fallbacks)

| Metric | B: rules only | C: LLM + protocol floor |
|---|---|---|
| Category accuracy | 58% | 89% (Wilson 95% interval about 81-94%) |
| Category macro-F1 | 0.591 | 0.876 |
| Severity exact / within one level | 30% / 53% | 68% / 90% |
| Under-triage | 57% | 7% (about 3-14%) |
| Over-triage | n/a | 25% (12 low and 4 medium rated higher; 9 high rated critical) |
| Critical recall / precision | 9/31 recall | 31/31 recall, 31/41 = 76% precision |
| McNemar (category) | only B right 7, only C right 38, p < 0.001 | |

Per language (B / C): en 60/90 (n=58), hi 50/100 (n=8), hi-en 71/76 (n=17), pa 29/100 (n=7), pa-en 50/90 (n=10).
Caveats: author and labeller of the scenarios is itself a language model; the critical share (33%) is far higher than
real data; "0/31 critical missed" is compatible with a true miss rate of up to about 10%; B is a quickly written
baseline; per-language cells are small. The test split was inspected after this run, so any later change to the
rules, prompt or floor must be reported as post-hoc.
Dataset: 150 scenarios (50 dev, 100 test); critical 49, high 42, low 35, medium 24; en 84, hi-en 26, pa-en 16, hi 13, pa 11.

## 8. Floor ablation (post-hoc; correction to section 1)

Severity, test (100): LLM alone exact 77% / under 8% / over 15% / critical recall 100%;
LLM + original floor 68% / 7% / 25% / 100%. The original floor changed 13 answers: helped 1, hurt 12.
Dev (50): LLM alone 74% / 10% / 16% / 94.4%; with original floor 64% / 10% / 26% / 94.4%; changed 6: helped 0, hurt 6.
The original floor did not add critical recall, so the statement in section 1 that the keyword floor contributes
to the critical-case result is not supported by the 150-scenario data.
Change: the floor was narrowed to unambiguous life-threat phrases (critical list only; the broad "high" keyword list
was removed from the floor). The rules-only baseline B is unchanged.
Process: the change was designed after the test split had been inspected, so the post-change test number is
post-hoc, not a clean holdout. A fresh holdout batch is needed for a clean measurement.
Limits: eight author-written injection cases cannot establish injection robustness; the floor is kept as
defence in depth, not as proven protection.

## 9. After narrowing the floor (post-hoc for test; dev supports the change independently)

| | Dev (50) | Test (100) |
|---|---|---|
| LLM alone: severity exact / under / over | 74% / 10% / 16% | 77% / 8% / 15% |
| LLM + narrow floor: same | 74% / 10% / 16% | 77% / 8% / 15% |
| Floor changed the answer | 0 | 1 (hurt 1) |
| Critical recall / precision | 17/18 / 77% | 31/31 / 76% |
| Category accuracy / macro-F1 | 84% / 0.743 | 89% / 0.876 |
| Severity within one level | 100% | 99% |

Test severity exact 77% has a 95% interval of roughly 68-84%; category accuracy 89% roughly 81-94%.
B (rules only) is unchanged at 28% (dev) and 30% (test) severity exact.
The narrow floor neither helps nor hurts on these scenarios; it is retained as defence in depth for injection.
Main residual weakness: over-triage by the LLM (9 of 31 test "high" reports rated critical; 24% of predicted
criticals are not critical). Dev "other" category: 1 of 8 correct, mostly ambiguous hazards.

## 10. Dynamic arrivals (200 trials not run; 30 trials per rate, seed 7, 12 ambulances, 2 h of Poisson arrivals)

Response time = report arrival until a unit reaches the scene (OSRM road times). Policies: A FIFO + nearest unit,
B severity priority (ties by arrival) + nearest unit, C weighted Hungarian over waiting incidents and free units,
D like C with weights growing with waiting time. No reassignment of moving units.

| Rate | Policy | All mean s | Critical mean s | Critical within 15 min | Low mean s | Low p95 s |
|---|---|---|---|---|---|---|
| 20/h | A / B / C / D | 235 | 248 / 245 / 244 / 245 | 100% | 226 / 233 / 232 / 233 | 426 / 437 / 427 / 437 |
| 30/h | A | 481 | 499 | 83.9% | 464 | 1229 |
| 30/h | B | 472 | 336 | 99.6% | 660 | 2118 |
| 30/h | C | 444 | 330 | 99.3% | 607 | 2147 |
| 30/h | D | 469 | 335 | 99.6% | 627 | 1955 |
| 40/h | A | 1099 | 1147 | 43.0% | 1128 | 2618 |
| 40/h | B | 1089 | 401 | 99.7% | 2474 | 5370 |
| 40/h | C | 972 | 384 | 98.2% | 2206 | 5931 |
| 40/h | D | 1088 | 399 | 99.7% | 2239 | 4635 |

Paired differences in seconds (negative = first policy faster; Wilcoxon, uncorrected):
- B vs A, 30/h and 40/h: critical -144.6 and -735.4 (p < 0.0001); low +184.9 and +1322.9 (p < 0.0001); all -8.2 (p = 0.40) and -9.6 (p = 0.28).
- C vs B: all -24.7 (p = 0.0001) and -114.1 (p < 0.0001); critical -5.8 (p = 0.13) and -15.0 (p = 0.058); low -48.3 (p = 0.003) and -258.7 (p < 0.0001).
- D vs C: all +22.0 (p = 0.0003) and +112.6 (p < 0.0001); critical +6.0 (p = 0.24) and +12.9 (p = 0.13); low +16.0 (p = 0.20) and +31.8 (p = 0.32).

Findings: at 20/h policy does not matter; from 30/h priority ordering protects critical incidents but shifts waiting onto
low-severity incidents (all-incident mean unchanged); weighted Hungarian does not significantly improve critical response
over plain priority but improves the all-incident and low-severity means; aging narrows the low-severity tail (p95 4635 vs
5931 s at 40/h) at the cost of a higher all-incident mean.
Open hypothesis (untested): C's gain over B comes from distance tie-breaking within a severity class, because the
objective w*(t - 100001) makes the choice of served incidents lexicographic by severity. A policy "highest severity, then
nearest incident" (B2) is needed to test it.
Limits: zero dispatch delay, return trip equals outbound trip, no traffic or hand-over time, ambulances only, assumed
severity mix, scene time and arrival rates, no reassignment, uncorrected tests, p95 and worst values pooled over 30 trials.
