# TODO

Project: X DM Image Safety Filter Prototype (v0.1)

## Status legend

- [ ] Not started
- [x] Done / decided
- [-] Dropped / out of scope

---

## 1. Product scope freeze

- [x] v0.1 is fail-open
- [x] 1:1 DMs only
- [x] Future events only
- [x] Media attachments only
- [x] Text-only DMs are log-only
- [x] Violence & Gore only
- [x] Unsafe = LlavaGuard rating "unsafe" + category O2
- [x] Block if any image/frame is unsafe
- [x] GIF/video: 1 fps from t=1s up to 12s, capped by duration
- [x] Video/GIF > 25 MB falls back to preview image if available
- [x] Unsupported/unknown attachment types are logged and ignored
- [x] Local DB is system history/cache, not X truth

---

## 2. Canonical deployment decisions

- [x] Single X account per machine
- [x] Single Windows host
- [x] Single public hostname
- [x] Exclusive installer-owned Traefik instance on host
- [x] Canonical ingress = DuckDNS + Traefik + public HTTPS on 443
- [x] TLS-ALPN-01 only
- [x] No DNS-01 fallback in v0.1
- [x] No Cloudflare Tunnel in v0.1
- [x] No nginx as canonical path
- [x] Traefik terminates TLS and proxies HTTP to `127.0.0.1:8080`
- [x] Traefik exposes only exact `Host(<duckdns-host>) && Path("/webhooks/x")`
- [x] Traefik service is managed separately from `dmguard`
- [x] Service manager = Servy
- [x] Traefik service account = LocalSystem
- [x] Traefik starts automatically on boot
- [x] `dmguard` depends on Traefik service
- [x] Public route is 443-only
- [x] Windows Firewall rule allows inbound 443 for Traefik only

---

## 3. Filesystem conventions

- [x] Binaries/templates live under `C:\Program Files\XDMModerator\`
- [x] Mutable runtime state lives under `C:\ProgramData\XDMModerator\`
- [x] SQLite DB path = `C:\ProgramData\XDMModerator\state.db`
- [x] Main config path = `C:\ProgramData\XDMModerator\config.yaml`
- [x] Secrets path = `C:\ProgramData\XDMModerator\secrets.bin`
- [x] Setup state path = `C:\ProgramData\XDMModerator\setup_state.json`
- [x] Setup log path = `C:\ProgramData\XDMModerator\setup.log`
- [x] Runtime logs path = `C:\ProgramData\XDMModerator\logs\`
- [x] Traefik runtime dir = `C:\ProgramData\XDMModerator\traefik\`
- [x] Traefik templates dir = `C:\Program Files\XDMModerator\traefik\templates\`

---

## 4. Traefik template layout

- [x] Static template path = `traefik-static.yml.tpl`
- [x] Route templates = `routes-normal.yml.tpl` and `routes-debug.yml.tpl`
- [x] Generated static config = `traefik-static.yml`
- [x] Generated routes file = `routes.yml`
- [x] ACME state file = `acme.json`
- [x] `routes.yml` is installer-owned and generated from exactly two templates
- [x] `routes.yml` is atomically replaced on update
- [x] Route templates use fixed placeholders only
- [x] Static template uses fixed placeholders only
- [x] Traefik dashboard/API is debug/setup-only
- [x] Dashboard/API auto-disables after successful setup
- [x] Debug dashboard binds to fixed local-only port
- [x] Debug dashboard port is configurable, default 8081
- [x] `routes.yml` changes are hot-reloaded
- [x] Traefik restarts only when static config changes

---

## 5. Runtime API surface

- [x] Implement `GET /webhooks/x` for CRC
- [x] Implement `POST /webhooks/x` for webhook deliveries
- [x] Implement `GET /health`
- [x] Implement `GET /version`
- [ ] Implement optional local-only `/webhooks/test` in debug mode
- [x] Disable FastAPI docs/OpenAPI unless debug
- [x] Keep public app surface minimal

---

## 6. Webhook receiver rules

- [x] Request body limit = 1 MB
- [x] Bad signature => reject
- [x] Invalid JSON => reject
- [x] Oversized payload => reject
- [x] Signed but unsupported payload shape => 200 OK, ignore
- [x] Only MessageCreate events are enqueued
- [x] Enqueue all MessageCreate events, even if no media
- [x] Persist trimmed subset for valid events
- [x] Rejected requests go to `rejected_requests`
- [x] Implement signature verification
- [x] Implement idempotent enqueue by `event_id`
- [x] Implement trimmed event persistence
- [x] Implement rejected request persistence

---

## 7. SQLite schema and state tables

- [x] `webhook_events`
- [x] `jobs`
- [x] `job_errors`
- [x] `rejected_requests`
- [x] `blocked_senders`
- [x] `block_failed_senders`
- [x] `allowed_senders`
- [x] `moderation_audit`
- [x] `kv_store`
- [x] `jobs.event_id` is `NOT NULL + UNIQUE + FK`
- [x] `jobs.status` = `queued | processing | done | error | skipped`
- [x] `jobs.stage` stays on last failed stage when status=`error`
- [x] `jobs.attempt` is current-stage attempt counter
- [x] `allowed_senders` fields = `sender_id, created_at, source_event_id`
- [x] Implement schema bootstrap
- [x] Implement repository layer
- [x] Implement explicit indexes
- [x] Add tests for schema and repository behavior

---

## 8. Job scheduler and worker behavior

- [x] Sequential worker only
- [x] Poll every 5 seconds
- [x] Runnable jobs = `status='queued' AND next_run_at <= now`
- [x] Order by `next_run_at ASC, job_id ASC`
- [x] Claim job in one transaction
- [x] Retry from failed stage
- [x] Stage attempt counter resets on stage advance
- [x] General retry backoff = 10s, 60s, 300s
- [ ] 429 does not consume an attempt
  Current repo state: `schedule_429_retry` exists, but the worker does not route real 429 failures through it yet.
- [ ] Queue cap = 5000
  Current repo state: no enqueue-time queue-length cap is enforced in the webhook path yet.
- [ ] Queue overflow drops newest incoming job
  Current repo state: there is no logic to reject the newest incoming job when a queue limit is reached.
- [ ] Queue overflow is tracked with counters only
  Current repo state: `/health` reads drop counters from `kv_store`, but the enqueue/worker path does not populate them.
- [x] Implement worker loop
- [x] Implement transactional claim/update logic
- [x] Implement retry scheduling
- [ ] Implement queue overflow counters
  Current repo state: counter keys are exposed in `/health` and covered by tests with seeded data, but no production code increments them.
- [x] Add scheduler tests

---

## 9. Startup recovery and health

- [x] Stale `processing` jobs older than 30 minutes reset to `queued` on startup
- [x] Recovery is logged to `dmguard.log` only
- [x] `/health` includes configured/ready/liveness and queue/error/drop counters
- [x] `/version` includes app + dependency versions
- [x] Implement stale-processing recovery
- [x] Implement `/health` aggregation
- [x] Implement `/version`
- [x] Add startup recovery tests

---

## 10. X API integration

- [x] DM lookup endpoint = `GET /2/dm_events/{event_id}`
- [x] Shared X API timeout = 10 seconds
- [ ] Proactive token refresh
  Current repo state: `XClient` uses a static bearer token and does not run a refresh flow before requests.
- [ ] Token expiry metadata stored in SQLite
  Current repo state: `token_expiry` appears only as a generic `kv_store` value in repository tests, not as runtime-managed metadata.
- [ ] Refresh failure marks system misconfigured
  Current repo state: refresh failure handling is not present because token refresh is not implemented.
- [x] Implement secret loader
- [x] Implement X API client
- [x] Implement DM lookup DTO parsing
- [ ] Implement proactive refresh
  Current repo state: request construction, timeout handling, and HTTP error parsing are implemented; runtime refresh remains missing.
- [x] Add tests for request construction and parsing

---

## 11. Media pipeline

- [x] Use attached media only
- [x] Photos supported
- [x] GIFs/videos supported
- [x] GIFs use same multi-frame extraction logic as video
- [x] Media temp files live under ProgramData tmp dir
- [x] Temp filenames include plain event_id
- [x] Temp files deleted after each job
- [x] No image size cap in MVP
- [x] Video/GIF cap = 25 MB
- [x] Over-cap video/GIF => preview image fallback if available
- [x] Implement attachment dispatch
- [x] Implement authenticated media download
- [x] Implement temp file lifecycle
- [x] Implement frame extraction
- [x] Add media pipeline tests

---

## 12. Classifier subsystem

- [x] Classifier runs as on-demand child process
- [x] IPC = temp JSON input file + JSON stdout
- [x] Single total timeout = 180 seconds
- [x] Kill classifier on timeout
- [x] `selftest` supports image and video
- [x] `--force-safe` returns rating=safe, category="NA: None applying"
- [x] `--force-unsafe` returns rating=unsafe, category="O2: Violence, Harm, or Cruelty", trigger_frame_index=0 (video) / None (image)
- [x] Classifier stderr is captured and written to `classifier.log`
- [x] Implement subprocess contract
- [x] Implement fake classifier mode for early tests
- [x] Integrate real LlavaGuard inference
  Current repo state: `classifier_backend: llavaguard` selects the CUDA-backed `AIML-TUDA/LlavaGuard-v1.2-0.5B-OV-hf` runtime while forced selftests and test fixtures still use the fake classifier path.
- [x] Implement selftest CLI
- [x] Add classifier contract tests

---

## 13. Moderation engine

- [x] Unsafe if LlavaGuard rating == "unsafe" and category O2
- [x] Allowlist short-circuit happens before DM lookup
- [x] First safe media DM adds sender to `allowed_senders`
- [x] Allowlisted sender jobs are still recorded
- [x] Allowlisted sender jobs end with `status='skipped'`
- [x] `skipped` means allowlist skip only
- [x] Block success adds sender to `blocked_senders`
- [x] Block failure updates `block_failed_senders`
- [x] Fail-open posture for v0.1
- [x] Implement moderation decision engine
- [x] Implement sender-state transitions
- [x] Implement allowlist fast path
- [x] Implement block cooldown logic
- [x] Add moderation flow tests

---

## 14. Audit and error history

- [x] `job_errors` remains error-only
- [x] `moderation_audit` is append-only
- [x] `moderation_audit.outcome` enum =
  - safe
  - blocked
  - skipped_allowlist
  - text_only_logged
  - error
- [x] `moderation_audit` uses typed columns only
- [x] `moderation_audit` may allow multiple rows per job in schema
- [ ] MVP behavior appends one final audit row per job
  Current repo state: moderation outcomes append audit rows, but dispatch exceptions that end in `job_errors` do not always get a final audit row.
- [x] `moderation_audit` retention = 30 days
- [x] `moderation_audit` index = `created_at` only
- [x] Implement `job_errors`
- [x] Implement `moderation_audit`
- [ ] Write final audit row on terminal job outcome
  Current repo state: safe, blocked, skipped_allowlist, text_only_logged, and block-failure error outcomes are audited; classifier timeout/error paths still rely on `job_errors` only.
- [x] Add audit and error history tests

---

## 15. Retention and pruning

- [x] Retention = 30 days
- [x] Never auto-prune:
  - `allowed_senders`
  - `blocked_senders`
  - `block_failed_senders`
- [x] Only prune terminal jobs (`done`, `error`)
- [x] Prune order is explicit
- [x] `job_errors` are deleted before terminal jobs
- [x] Implement prune command/function
- [x] Implement daily prune trigger
- [x] Add pruning tests

---

## 16. Setup orchestration

- [x] Setup is rerunnable and stateful
- [x] `setup_state.json` is non-secret metadata only
- [x] `setup_state.json` stores latest run only
- [x] Setup tracks per-stage artifacts
- [x] Stage invalidation is automatic
- [x] `--verbose` explains invalidation/progress only
- [ ] Rollback is best-effort
  Current repo state: setup writes state and logs, but no setup rollback implementation exists yet.
- [ ] Rollback attempts = 3 with 1s, 5s, 10s
  Current repo state: no setup rollback retry loop exists yet.
- [ ] Continue even if rollback fails
  Current repo state: rollback failure handling is not present because setup rollback is not implemented yet.
- [x] Setup writes append-only `setup.log`
- [x] `setup.log` always redacts secrets
- [x] Implement setup state machine
- [x] Implement stage invalidation
- [x] Implement verbose output
- [x] Implement setup log writer
- [x] Add setup-state tests

---

## 17. Services and edge orchestration

- [x] Traefik is the canonical bundled edge
- [x] Traefik is managed as a separate Windows service
- [x] Service manager = Servy
- [x] `dmguard` is also managed by Servy
- [x] Traefik is installed/started before `dmguard`
  Current repo state: `setup` now installs both services via Servy and starts Traefik before starting `dmguard`.
- [x] `dmguard` only installs after TLS + public reachability succeed
  Current repo state: `setup` now runs TLS and public-reachability verification before installing/starting the `dmguard` service.
- [x] Generate Traefik service definition
- [x] Generate `dmguard` service definition
- [ ] Implement service install/start/update logic
  Current repo state: service-definition generation plus install/start are implemented through Servy; explicit update semantics are not separately verified.
- [x] Add service config generation tests

---

## 18. Setup flow implementation

- [x] User inputs come from prompts and flags, not a user-authored config file
- [x] `config.yaml` is installer-authored, runtime-read, non-secret config
- [x] Public HTTPS reachability is checked before webhook registration
  Current repo state: `setup` now runs the public HTTPS probe before the webhook registration step.
- [ ] Unsupported environment => setup fails
  Current repo state: non-Windows environments now skip the Windows-only ingress stages instead of failing through a dedicated preflight rejection.
- [x] Implement setup subcommands (`setup`, `reset --force`, `warmup`, `status`, `status --full`)
- [x] Add setup CLI tests
- [ ] Implement preflight stage
  Current repo state: `setup` records the `preflight` stage in `setup_state.json`, but no environment validation step runs yet.
- [x] Implement local config stage
  Current repo state: `setup` writes `config.yaml` and marks `local_config` done inside `dmguard setup`.
- [x] Implement X auth stage
  Current repo state: `setup` collects and writes `secrets.bin` and marks `x_auth` done inside `dmguard setup`.
- [x] Implement DuckDNS stage
  Current repo state: `setup` now updates DuckDNS and records the installer-owned `duckdns.txt` artifact.
- [x] Implement Traefik stage
  Current repo state: `setup` now renders Traefik runtime artifacts, initializes `acme.json`, and writes installer-owned service definitions as a stage.
- [x] Implement TLS stage
  Current repo state: `setup` now verifies HTTPS reachability as the TLS gate before proceeding to webhook registration.
- [x] Implement public reachability stage
  Current repo state: `setup` now records public HTTPS reachability as an executed stage.
- [x] Implement X webhook registration stage
  Current repo state: `setup` now ensures a matching X webhook exists and records its metadata artifact.
- [x] Implement model warmup stage
  Current repo state: `setup` now invokes model warmup as part of the operational stage flow.
- [x] Implement app service stage
  Current repo state: `setup` now installs/starts the Traefik and `dmguard` services and marks `app_service` done only after both report `Running`.

---

## 19. Admin CLI

- [x] `dmguard.exe allowlist add --user-id <id> --source-event-id <id>`
- [x] `dmguard.exe allowlist remove --user-id <id>`
- [x] `dmguard.exe blockstate remove --user-id <id>`
- [x] `selftest`
- [x] `readycheck`
- [x] Implement allowlist add/remove
- [x] Implement blockstate remove
- [x] Implement selftest
- [x] Implement readycheck
- [x] Add CLI tests

---

## 20. Testing plan

### Unit / component
- [x] Config parsing tests
- [x] Path policy tests
- [x] Schema bootstrap tests
- [x] Repository tests
- [x] Scheduler tests
- [x] Retry/backoff tests
- [x] Signature validation tests
- [x] CRC tests
- [x] Media pipeline tests
- [x] Classifier contract tests
- [x] Moderation decision tests
- [x] Audit/prune tests
- [x] Setup state tests

### Integration
- [x] Valid webhook -> safe media -> allowlist
- [x] Valid webhook -> unsafe media -> block
- [x] Allowlisted sender -> skipped before DM lookup
- [x] Text-only DM -> text_only_logged
- [x] Classifier failure -> error
- [x] Stale processing recovery after restart

### Manual environment validation
- [ ] DuckDNS resolves to current public IP
  Current repo state: `status --full` includes a DuckDNS DNS-resolution check; external/manual validation is still open.
- [ ] Public 443 reachable from outside
  Current repo state: `status --full` includes an HTTPS probe; outside-in network validation is still open.
- [ ] TLS-ALPN-01 certificate issued successfully
- [ ] Traefik proxies only `/webhooks/x`
  Current repo state: template and service-definition generation are covered by tests, but no live Traefik environment validation is checked in.
- [ ] X webhook registration succeeds
- [ ] CRC succeeds
  Current repo state: the local CRC endpoint is covered by automated tests; external/manual validation is still open.
- [ ] Real DM media path works end-to-end
  Current repo state: mocked end-to-end acceptance tests exist, but no real X webhook/media environment run is checked in.

---

## 21. Known risks / non-goals

- [x] Public HTTPS on a Windows host is an accepted MVP risk
- [x] DM media fetch reliability is a known integration risk
- [x] Host-level Traefik exclusivity is an accepted MVP limitation
- [x] No attempt is made to synchronize local sender state with X truth
- [x] No GUI/admin UI in v0.1
- [x] No containerization in v0.1
