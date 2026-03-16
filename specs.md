> **Frozen v0.1 design reference.** This document captures the build blueprint and
> implementation prompts as agreed during the design phase. It is not updated to reflect
> implementation changes — see the codebase and [README.md](README.md) for the current state.

Below is a **developer-ready build blueprint** for the frozen **v0.1** you decided in this conversation, followed by a **right-sized implementation sequence** and then a **series of code-generation prompts** that build on one another safely.

I’m treating these as fixed product choices from our discussion:

* single X account, single Windows host, 1:1 DMs only
* future events only
* fail-open for v0.1
* attached media only
* local LlavaGuard-based moderation
* auto-block on unsafe
* local allow/block state is **system history/cache**, not X truth
* canonical ingress is **DuckDNS + Traefik + public HTTPS on 443**, with Traefik exposing only `/webhooks/x`

A few external constraints shape the implementation:

* X webhooks must be **public HTTPS**, must return **200 OK**, should respond within **10 seconds**, must support **CRC**, and the webhook URL **cannot include a port**. ([X Developer Platform][1])
* The DM lookup endpoint is `GET /2/dm_events/{event_id}` and supports `attachments.media_keys`, `media.fields`, `preview_image_url`, `url`, and `variants`, which is exactly what the media pipeline needs. ([X Developer Platform][2])
* LlavaGuard v1.2 is a **0.5B** image-safety model with a full O1–O9 taxonomy; the system acts on **O2 (Violence, Harm, or Cruelty)**, which matches the chosen moderation scope. ([Hugging Face][3])
* Traefik can be installed as a **binary**, distinguishes **startup/static** config from **routing/dynamic** config, and routing config can be hot-reloaded. ([Traefik Docs][4])
* Traefik’s **TLS-ALPN-01** ACME flow requires public reachability on **port 443**, which matches the final webhook requirement and supports the simplified ingress story. ([Traefik Docs][5])
* Servy can run arbitrary executables as Windows services, set dependencies/env vars, and manage logs/recovery, which fits both `dmguard` and Traefik. ([GitHub][6])

# 1. Build blueprint

## 1.1 System boundaries

Build three deployable layers:

1. **Core app (`dmguard`)**

   * FastAPI app for `/webhooks/x`, `/health`, `/version`
   * async worker loop in the same process
   * SQLite-backed job queue and sender-state tables
   * local classifier subprocess runner
   * admin CLI commands

2. **Edge layer**

   * Traefik binary
   * installer-owned static template + two route templates
   * live `routes.yml` generated from normal/debug template
   * TLS termination on 443
   * exact public route: `Host(<duckdns-host>) && Path("/webhooks/x")`

3. **Setup/runtime management**

   * `configure.bat`
   * `setup_state.json`
   * `config.yaml` for non-secrets
   * `secrets.bin` for machine-scope DPAPI secrets
   * Servy-managed Windows services for Traefik and `dmguard`

## 1.2 High-level architecture

Public traffic hits Traefik on 443. Traefik forwards only `/webhooks/x` to `http://127.0.0.1:8080`. The FastAPI receiver validates and enqueues quickly, then returns 200. The worker later does DM lookup, media retrieval, classification, and block/no-block decisions. Routing config lives separately from startup config because Traefik is built around that split. ([Traefik Docs][4])

## 1.3 Data model

Keep the data model intentionally split by responsibility:

* **Execution state**

  * `webhook_events`
  * `jobs`

* **Error history**

  * `job_errors`

* **Current local sender state**

  * `allowed_senders`
  * `blocked_senders`
  * `block_failed_senders`

* **Audit history**

  * `moderation_audit`

* **Rejected ingress**

  * `rejected_requests`

Important rules:

* `jobs.event_id` is `NOT NULL`, FK to `webhook_events(event_id)`, and `UNIQUE`
* one webhook event maps to one job in v0.1
* `jobs.status` = `queued | processing | done | error | skipped`
* `jobs.stage` stays on the last failed stage when status is `error`
* retries stay `queued` with future `next_run_at`

## 1.4 Core moderation rules

Implement exactly these rules first:

* text-only DM → `text_only_logged`
* unknown/unsupported attachment types → log and ignore
* photo set → classify each, block if any unsafe
* GIF/video → extract 1 fps from `t=1..12`, capped by duration; block if any frame unsafe
* video/GIF > 25 MB → use preview image if available, else error
* allowlisted sender → create job, skip before DM lookup, status `skipped`
* safe first media DM → add sender to `allowed_senders`
* unsafe media → attempt block
* block success → add sender to `blocked_senders`
* block failure → update `block_failed_senders` retry ban

## 1.5 Failure model

Do **not** over-tighten v0.1. Keep the failure behavior aligned with your product hypothesis:

* lookup failure → error
* media download failure → error
* classifier failure → error
* block API failure → error

That is deliberately **fail-open** in v0.1.

## 1.6 Queue / worker model

Keep the worker simple and deterministic:

* sequential only
* poll every 5s
* runnable query:

  * `status='queued' AND next_run_at <= now`
  * ordered by `next_run_at ASC, job_id ASC`
* per-stage attempt counter in `jobs.attempt`
* stage retry backoff:

  * 10s → 60s → 300s
* 429 does not consume an attempt
* stale `processing` jobs older than 30 minutes are reset to `queued` at startup

## 1.7 Ingress / setup model

Canonical path only:

* DuckDNS hostname
* Traefik binary installed on host
* TLS-ALPN-01 only
* public reachability check before X webhook registration
* if 443/TLS/public reachability fails, setup fails

Do not reintroduce Cloudflare or DNS-01 complexity into v0.1.

## 1.8 Testing philosophy

Test pyramid:

1. **Unit tests**

   * parsing
   * decision rules
   * retry math
   * state transitions
   * template rendering
   * config loading
   * file-path policy

2. **Component tests**

   * webhook receiver with signed/invalid requests
   * queue scheduler
   * SQLite repository layer
   * media pipeline with mocked X responses
   * classifier subprocess contract with forced-safe/forced-unsafe

3. **Integration tests**

   * FastAPI + worker + SQLite
   * end-to-end “safe media → allowlist”
   * end-to-end “unsafe media → block”
   * restart recovery of stale processing jobs

4. **Manual environment tests**

   * Traefik 443 reachability
   * ACME/TLS-ALPN issuance
   * X webhook registration + CRC
   * public webhook delivery

# 2. Iterative chunking

## Round 1: large chunks

1. Repository, config, paths, logging
2. SQLite schema and repositories
3. Job queue and worker state machine
4. Webhook receiver and ingress validation
5. X API client and DM lookup
6. Media pipeline and classifier subprocess
7. Moderation engine and sender-state tables
8. Audit/pruning/recovery
9. Traefik + service templates
10. Setup orchestration
11. Admin CLI
12. End-to-end hardening

## Round 2: smaller, safer chunks

These are the right-sized implementation increments:

1. Project skeleton, typed config objects, path policy, log setup
2. DB bootstrap, schema creation, indexes, repo layer
3. Job status/stage machine and dequeue logic
4. FastAPI app with `/health`, `/version`, lifecycle hooks
5. Webhook CRC + signature validation + enqueue
6. X auth/secrets abstractions + DM lookup client
7. Media downloader + attachment dispatch
8. Classifier subprocess contract + selftest
9. Moderation decisions + sender-state updates
10. Audit logging + prune + stale-processing recovery
11. Traefik template rendering and local service abstractions
12. `configure.bat` stage machine + state file + setup logging
13. Admin CLI (`allowlist add/remove`, `blockstate remove`)
14. End-to-end assembly and acceptance tests

That is small enough to test safely, but large enough that every step leaves the repo in a working state.

# 3. Code-generation prompts

Use these in order. Each one assumes the previous one is already complete and passing tests.

## Prompt 1 — repository skeleton and app foundation

```text
You are implementing Prompt 1 of a staged build for a Windows-hosted X DM media moderation prototype.

Goal:
Create the repository skeleton and foundational Python application structure for Python 3.12.13. Use FastAPI, httpx, aiosqlite, and pytest. Do not implement business logic yet.

Requirements:
- Create a clean package layout for:
  - app config
  - paths
  - logging
  - FastAPI app bootstrap
  - worker bootstrap placeholder
  - DB bootstrap placeholder
  - CLI placeholder
- Add strict typing and reasonable dataclasses or Pydantic models for non-secret config.
- Establish the Windows path convention:
  - Program Files for binaries/templates
  - ProgramData for mutable state
- Add a config loader for installer-authored non-secret config.yaml.
- Add logging bootstrap for:
  - dmguard.log
  - classifier.log
- Add /health and /version route placeholders returning minimal JSON.
- Add tests first for:
  - path resolution rules
  - config parsing
  - logger initialization
  - app creation
- Keep all secrets and setup metadata out of this prompt.
- No business logic, no DB schema, no X API code yet.

Acceptance:
- pytest passes
- app boots locally
- code is formatted and organized for later prompts
- nothing in this prompt is orphaned
```

## Prompt 2 — SQLite schema bootstrap and repositories

```text
You are implementing Prompt 2. Build on the existing skeleton only.

Goal:
Add SQLite bootstrap, create-if-missing schema creation, and repository abstractions for the MVP tables.

Requirements:
- Implement schema creation for:
  - webhook_events
  - jobs
  - job_errors
  - rejected_requests
  - blocked_senders
  - block_failed_senders
  - allowed_senders
  - moderation_audit
  - kv_store
- Encode these important rules:
  - jobs.event_id is NOT NULL, UNIQUE, and FK to webhook_events(event_id)
  - jobs.status supports: queued, processing, done, error, skipped
  - jobs.attempt is the current-stage attempt counter
- Add the agreed explicit indexes, especially the dequeue index on jobs(status, next_run_at, job_id).
- Create repository modules with small focused methods, not one giant DAO.
- Add tests first for:
  - schema creation
  - unique event_id → one job rule
  - basic inserts/reads
  - index-bearing dequeue query shape
- Do not implement worker logic yet.
- Do not implement pruning yet.
- Keep the repositories ergonomic for later prompts.

Acceptance:
- DB initializes from scratch
- repository methods are covered by tests
- no migration framework is introduced
```

## Prompt 3 — job state machine and worker scheduler core

```text
You are implementing Prompt 3. Build only on the existing code.

Goal:
Implement the job state machine and worker scheduler core, without X API or classification logic.

Requirements:
- Add explicit stage enum handling:
  - fetch_dm
  - download_media
  - classify
  - block
- Implement job claim in one DB transaction:
  - set status=processing
  - set started_at/updated_at
  - increment attempt for the current stage
- Implement dequeue of runnable jobs:
  - status='queued'
  - next_run_at <= now
  - ordered by next_run_at ASC, job_id ASC
- Implement stage advancement:
  - reset attempt to 0 on new stage
- Implement terminal transitions:
  - done
  - error
  - skipped
- Implement backoff scheduling for general transient retries:
  - 10s, 60s, 300s
- Add tests first for:
  - claim transaction behavior
  - stage advancement
  - attempt reset semantics
  - retry scheduling
  - skipped status semantics
- Use pure worker/domain logic and DB only.
- No external API calls yet.

Acceptance:
- the worker scheduler logic is fully unit-tested
- state transitions are deterministic and explicit
```

## Prompt 4 — FastAPI lifecycle, stale-processing recovery, and health/version

```text
You are implementing Prompt 4.

Goal:
Turn the app into a real service shell with lifecycle hooks, stale-processing recovery, and meaningful /health and /version endpoints.

Requirements:
- Start the worker loop from FastAPI lifespan/startup.
- On startup, recover stale processing jobs older than 30 minutes:
  - reset them to queued
  - keep same stage and attempt
  - assign fresh next_run_at
  - log the recovery to dmguard.log only
- Implement /health to include:
  - ok
  - configured
  - ready
  - queued_jobs
  - processing_jobs (0/1)
  - error_jobs_last_24h
  - dropped_jobs_total
  - dropped_jobs_last_24h
  - last_drop_at
- Implement /version with cached version/build/dependency info.
- Add tests first for:
  - stale job reset
  - health aggregation
  - version response shape
- Keep configured/ready plumbing minimal now; later prompts can fill in details.

Acceptance:
- service startup is testable
- stale-processing recovery works
- /health and /version are meaningful and stable
```

## Prompt 5 — webhook receiver, CRC, request validation, and enqueue

```text
You are implementing Prompt 5.

Goal:
Implement the public webhook ingress behavior for /webhooks/x.

Requirements:
- Add GET /webhooks/x for CRC:
  - respond with the HMAC-SHA256 CRC response_token using the configured consumer secret
- Add POST /webhooks/x:
  - enforce 1 MB request size limit
  - parse JSON
  - validate X signature via x-twitter-webhooks-signature
  - accept signed but unsupported payload shapes with 200 and ignore
  - persist valid MessageCreate events into webhook_events
  - create one job per event
- Use the current payload-extraction rule:
  - support extracting event_id from legacy or v2-shaped payloads
  - filter on event_type == "MessageCreate"
- Persist rejected requests into rejected_requests with metadata only.
- Add tests first for:
  - CRC correctness
  - bad signature rejection
  - invalid JSON rejection
  - oversized body rejection
  - signed unsupported shape returns 200 and no enqueue
  - valid MessageCreate enqueues exactly one job
- Keep the endpoint fast; do not do X lookup or classification inline.

Acceptance:
- webhook behavior is fully covered
- enqueue path is idempotent by event_id
- receiver remains fast and side-effect bounded
```

## Prompt 6 — secrets/auth abstraction and X DM lookup client

```text
You are implementing Prompt 6.

Goal:
Add secret-loading abstractions and the X API client needed for DM lookup.

Requirements:
- Add machine-scope DPAPI secret read/write abstraction interfaces, but keep setup-time writing minimal for now.
- Add a runtime secret loader for:
  - X access token
  - refresh token
  - consumer secret
  - app bearer
  - HF token placeholder
- Add X HTTP client abstraction with shared timeout support.
- Implement the GET /2/dm_events/{event_id} lookup client with the agreed query set:
  - attachments
  - created_at
  - dm_conversation_id
  - sender_id
  - text
  - expansions for attachments.media_keys and sender_id
  - media.fields for type/url/preview_image_url/variants
- Add tests first for:
  - request construction
  - auth header injection
  - response parsing into internal DTOs
  - unsupported/empty attachment handling
- Do not implement proactive refresh yet unless it is strictly needed by the client shape.

Acceptance:
- DM lookup is isolated behind a tested client interface
- internal DTOs are ready for the worker pipeline
```

## Prompt 7 — media pipeline and attachment dispatch

```text
You are implementing Prompt 7.

Goal:
Implement media selection and download behavior for attached media.

Requirements:
- Build attachment dispatch for:
  - photos
  - videos
  - animated GIFs
  - unsupported/unknown attachment types → log and ignore
- Download media using authenticated requests where appropriate.
- Enforce:
  - no image size cap for MVP
  - 25 MB cap for video/GIF
  - over-cap video/GIF falls back to preview image if present
- Store temp files only under the ProgramData tmp directory.
- Use plain event_id in temp filenames.
- Delete temp files after each job completes.
- Add tests first for:
  - photo selection
  - GIF/video preview fallback
  - oversize handling
  - unknown attachment handling
  - temp file lifecycle
- Keep frame extraction itself for the next prompt.

Acceptance:
- media pipeline returns normalized local file inputs for the classifier stage
- no persistence of media bytes beyond temp processing
```

## Prompt 8 — classifier subprocess contract and selftest

```text
You are implementing Prompt 8.

Goal:
Implement the classifier subprocess contract and local selftest tools.

Requirements:
- Define a JSON input contract for the classifier subprocess.
- Implement classifier subprocess invocation via temp JSON input file + JSON stdout.
- Implement timeout handling:
  - total classifier timeout 180s
  - kill process on timeout
- Capture stdout/stderr and write classifier stderr to classifier.log with path-safe logging.
- Add selftest CLI:
  - --image <path>
  - --video <path>
  - --force-safe
  - --force-unsafe
- Forced outputs:
  - force-safe: rating=safe, category="NA: None applying", trigger_frame_index=None
  - force-unsafe (video): rating=unsafe, category="O2: Violence, Harm, or Cruelty", trigger_frame_index=0
  - force-unsafe (image): rating=unsafe, category="O2: Violence, Harm, or Cruelty", trigger_frame_index=None
- Add tests first for:
  - subprocess contract parsing
  - timeout handling
  - forced safe/unsafe outputs
  - stderr capture
- Do not implement the actual LlavaGuard model load yet; use a deterministic fake classifier entrypoint first.

Acceptance:
- the classifier boundary is stable and testable
- the rest of the system can now integrate against it safely
```

## Prompt 9 — real classification integration and moderation engine

```text
You are implementing Prompt 9.

Goal:
Integrate the real moderation engine on top of the worker pipeline.

Requirements:
- Integrate the actual moderation rules:
  - text-only → text_only_logged
  - allowed_senders short-circuit before DM lookup
  - safe first media DM adds sender to allowed_senders
  - unsafe media triggers block attempt
  - blocked_senders skip future block calls forever
  - block_failed_senders enforce 24h retry ban
- Implement video/GIF frame extraction:
  - 1 fps
  - t=1..12
  - capped by duration
- Use the classifier subprocess output to decide:
  - unsafe if rating == "unsafe" and category starts with "O2"
- Append one final moderation_audit row per job in normal operation.
- Add tests first for:
  - allowlist fast path
  - safe → allowlist
  - unsafe → block attempt
  - block failed cooldown behavior
  - moderation_audit rows
- Keep the job fail-open behavior intact.

Acceptance:
- the full worker decision tree is implemented and covered
- sender-state tables update correctly
```

## Prompt 10 — pruning, recovery, and audit retention

```text
You are implementing Prompt 10.

Goal:
Implement retention, pruning, and related historical cleanup.

Requirements:
- Implement daily prune entrypoint for:
  1. job_errors for terminal jobs older than 30 days
  2. terminal jobs older than 30 days
  3. related old webhook_events whose terminal job is gone
  4. moderation_audit, rejected_requests, and other historical tables older than 30 days
- Never prune:
  - queued jobs
  - processing jobs
  - allowed_senders
  - blocked_senders
  - block_failed_senders
- Respect FK restrict behavior by pruning in the agreed order.
- Add tests first for:
  - prune order
  - no pruning of non-terminal jobs
  - terminal retention behavior
  - moderation_audit retention
- Keep implementation straightforward and observable through logs.

Acceptance:
- pruning is deterministic and safe
- no unfinished work is lost by retention logic
```

## Prompt 11 — Traefik templates and local service definitions

```text
You are implementing Prompt 11.

Goal:
Add the installer-owned Traefik template system and service-definition generation.

Requirements:
- Assume these shipped templates exist under Program Files:
  - traefik-static.yml.tpl
  - routes-normal.yml.tpl
  - routes-debug.yml.tpl
- Generate these live files under ProgramData:
  - traefik-static.yml
  - routes.yml
  - acme.json path reference
- Use only the agreed fixed placeholders:
  - PUBLIC_HOSTNAME
  - BACKEND_URL
  - DEBUG_DASHBOARD_PORT
  - ACME_EMAIL
  - ACME_STORAGE_PATH
  - TRAEFIK_LOG_PATH
- routes.yml is generated from exactly two templates:
  - normal
  - debug
- Use atomic replace for routes.yml writes.
- Validate generated YAML shape lightly before swapping.
- Add service-definition generation for:
  - Traefik service
  - dmguard service
  - dmguard depends on Traefik
- Add tests first for:
  - template rendering
  - atomic write behavior
  - debug/normal route generation
  - service definition generation
- Do not implement full batch setup yet.

Acceptance:
- edge/service artifacts can be generated reproducibly from inputs
```

## Prompt 12 — setup state machine and configure flow core

```text
You are implementing Prompt 12.

Goal:
Implement the core of the setup orchestrator and persisted setup-state model.

Requirements:
- Add setup_state.json handling with:
  - last_command
  - effective_args
  - per-stage status
  - timestamps
  - artifact lists
- Implement stage invalidation based on changed effective inputs.
- Keep setup metadata non-secret.
- Write append-only setup.log with secret redaction.
- Add --verbose mode that explains:
  - effective args
  - invalidated stages
  - overwritten/regenerated installer-owned artifacts
- Implement best-effort rollback metadata only:
  - 3 attempts
  - 1s, 5s, 10s
  - continue even if rollback still fails
- Add tests first for:
  - stage invalidation
  - setup state persistence
  - verbose output content
  - redaction in setup.log
- Do not try to finish the entire installer yet; just build the orchestrator core.

Acceptance:
- setup becomes a stateful pipeline rather than an ad hoc script
```

## Prompt 13 — concrete setup commands and admin CLI

```text
You are implementing Prompt 13.

Goal:
Finish the supported CLI surface for MVP.

Requirements:
- Implement admin CLI commands:
  - allowlist add --user-id <id>
  - allowlist remove --user-id <id>
  - blockstate remove --user-id <id>
  - selftest
  - readycheck
- Implement concrete setup subcommands:
  - setup
  - reset --force
  - warmup
  - status
- status default = local-only
- status --full = remote checks
- setup collects user inputs through prompts/flags; no user-authored config file path is introduced
- Add tests first for:
  - CLI parsing
  - state-table mutations
  - status output shape
  - reset safety behavior
- Keep naming honest: no command called “unblock” unless it truly talks to X.

Acceptance:
- the MVP operator surface is coherent, minimal, and internally consistent
```

## Prompt 14 — end-to-end wiring and acceptance tests

```text
You are implementing Prompt 14, the final MVP wiring step.

Goal:
Wire everything together into a coherent v0.1 system and add end-to-end acceptance tests.

Requirements:
- Connect:
  - FastAPI webhook receiver
  - worker loop
  - SQLite repositories
  - X lookup client
  - media pipeline
  - classifier subprocess
  - moderation engine
  - audit logging
- Add end-to-end tests for:
  - valid webhook → safe media → allowlist
  - valid webhook → unsafe media → block
  - allowlisted sender → skipped before DM lookup
  - text-only DM → text_only_logged
  - classifier failure → error
  - stale processing recovery after restart
- Add a small developer README section for running the app locally and running tests.
- Avoid wide refactors; prefer integrating the pieces built in earlier prompts.

Acceptance:
- all tests pass
- the repo reflects a complete v0.1 core implementation
- there is no hanging or orphaned code
```

This is the point where the project is ready to move from discovery into implementation.

[1]: https://docs.x.com/x-api/webhooks/introduction?utm_source=chatgpt.com "Webhooks - X"
[2]: https://docs.x.com/x-api/direct-messages/get-dm-event-by-id?utm_source=chatgpt.com "Get DM event by ID - X"
[3]: https://huggingface.co/AIML-TUDA/LlavaGuard-v1.2-0.5B-OV "LlavaGuard v1.2 0.5B"
[4]: https://doc.traefik.io/traefik/getting-started/configuration-overview/?utm_source=chatgpt.com "Traefik Configuration Documentation - Traefik"
[5]: https://doc.traefik.io/traefik/v2.1/https/acme/?utm_source=chatgpt.com "Let's Encrypt | Traefik | v2.1"
[6]: https://github.com/aelassas/servy?utm_source=chatgpt.com "GitHub - aelassas/servy: Turn Any App into a Native Windows Service - Full-Featured Alternative to NSSM, WinSW & FireDaemon Pro"
