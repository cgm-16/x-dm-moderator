# Issues TODO

GitHub repo: https://github.com/cgm-16/x-dm-moderator

## Status legend

- [ ] Not started
- [~] In progress
- [x] Done
- [-] Dropped / out of scope

---

## Milestone 1 — Project Skeleton

- [x] #1 Package structure + path policy — deps: _none_
- [x] #2 Config loader (Pydantic v2) — deps: #1
- [x] #3 Logging bootstrap — deps: #1
- [x] #4 FastAPI app skeleton — deps: #1, #2, #3

## Milestone 2 — Database

- [x] #5 DB connection management — deps: #1
- [x] #6 Schema DDL + indexes — deps: #5
- [x] #7 Repository layer — deps: #6

## Milestone 3 — Job State Machine

- [x] #8 Status/stage enums + transition logic (pure) — deps: _none_
- [ ] #9 Dequeue + claim transaction — deps: #7, #8
- [ ] #10 Retry scheduling — deps: #7, #8

## Milestone 4 — FastAPI Lifecycle

- [ ] #11 Stale processing recovery — deps: #7, #10
- [ ] #12 Worker loop + FastAPI lifespan — deps: #9, #11
- [ ] #13 /health aggregation — deps: #7, #12
- [ ] #14 /version endpoint — deps: #4

## Milestone 5 — Webhook Receiver

- [ ] #15 CRC endpoint — deps: #4, #2
- [ ] #16 Signature verification — deps: #4
- [ ] #17 Webhook POST + idempotent enqueue — deps: #7, #16
- [ ] #18 Rejected request persistence — deps: #7, #16

## Milestone 6 — X API Client

- [x] #19 Secrets loader interface — deps: #1
- [x] #20 X HTTP client — deps: #19
- [ ] #21 DM lookup client + DTOs — deps: #20

## Milestone 7 — Media Pipeline

- [ ] #22 Attachment dispatch — deps: #21
- [ ] #23 Media download + temp file lifecycle — deps: #20, #22
- [ ] #24 Video/GIF size cap + preview fallback — deps: #23

## Milestone 8 — Classifier

- [x] #25 Classifier subprocess contract + fake entrypoint — deps: #1
- [ ] #26 Subprocess runner + timeout — deps: #25
- [ ] #27 Selftest CLI — deps: #26

## Milestone 9 — Moderation Engine

- [ ] #28 Video/GIF frame extraction — deps: #23
- [ ] #29 Moderation decision logic — deps: #7, #26, #28
- [ ] #30 Sender state transitions — deps: #7, #29

## Milestone 10 — Audit + Pruning

- [ ] #31 Audit + job error recording — deps: #7, #29
- [ ] #32 Prune command — deps: #7
- [ ] #33 Daily prune trigger — deps: #32

## Milestone 11 — Traefik + Services

- [x] #34 Template rendering — deps: #1
- [ ] #35 Atomic routes.yml write + service definitions — deps: #34

## Milestone 12 — Setup Orchestration

- [x] #36 Setup state machine + setup_state.json — deps: #1
- [x] #37 Stage invalidation + verbose output — deps: #36
- [x] #38 Setup.log writer + secret redaction — deps: #36

## Milestone 13 — Setup Stages + Admin CLI

- [ ] #39 Setup subcommands — deps: #36, #37, #38
- [ ] #40 Admin CLI — deps: #7, #27, #30

## Milestone 14 — End-to-End

- [ ] #41 Full pipeline wiring — deps: #12, #17, #21, #24, #30, #31
- [ ] #42 End-to-end acceptance tests — deps: #41
- [ ] #43 Developer README section — deps: #42

---

## Dependency graph

```
#1 ──┬── #2 ──┐
     │        ├── #4 ──┬── #14
     │        │        ├── #15
     │        │        └── #16 ──┬── #17 ──┐
     │        │                  └── #18   │
     │        │                            │
     ├── #3 ──┘                            │
     │                                     │
     ├── #5 ── #6 ── #7 ──┬── #9 ──┐      │
     │                    │        │      │
     │                    │   #8 ──┘      │
     │                    │        │      │
     │                    ├── #10 ─┤      │
     │                    │        └── #11─┤
     │                    │               └── #12 ──┬── #13
     │                    │                         │
     │                    ├── (via #17) ─────────────┘
     │                    │
     │                    ├── #32 ── #33
     │                    │
     │                    └── (see sender/audit below)
     │
     ├── #19 ── #20 ──┬── #21 ── #22 ── #23 ──┬── #24
     │                │                        └── #28 ──┐
     │                └── (also feeds #23)               │
     │                                                    │
     ├── #25 ── #26 ──┬── #27 ── #40 (partial)           │
     │                └────────────────────────────── #29 ┤
     │                                                    │
     ├── #34 ── #35                               #7 ─────┤
     │                                                    │
     ├── #36 ──┬── #37 ── #39 (partial)          #29 ─┬── #30 ─┐
     │         └── #38 ── #39 (partial)               └── #31  │
     └─────────────────────────────────────────────────────────┤
                                                               │
#41 ← #12 + #17 + #21 + #24 + #30 + #31 ──────────────────────┘
#42 ← #41
#43 ← #42
```

---

## Parallel execution waves

Issues within the same wave have no interdependencies and can be worked in parallel.

| Wave | Issues |
|------|--------|
| 1 | #1, #8 |
| 2 | #2, #3, #5, #19, #25, #34, #36 |
| 3 | #4, #6, #37, #38 |
| 4 | #7, #14, #15, #16, #20, #26, #27, #35, #39 |
| 5 | #9, #10, #17, #18, #21, #32 |
| 6 | #11, #22, #40 |
| 7 | #12, #23 |
| 8 | #13, #24, #28, #33 |
| 9 | #29 |
| 10 | #30, #31 |
| 11 | #41 |
| 12 | #42 |
| 13 | #43 |

**Critical path:** #1 → #5 → #6 → #7 → #9 → #11 → #12 → #17 → #21 → #24 → #29 → #30/#31 → #41 → #42 → #43
