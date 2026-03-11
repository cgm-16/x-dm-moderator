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
- [x] Unsafe threshold = 0.90
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

- [ ] Implement `GET /webhooks/x` for CRC
- [ ] Implement `POST /webhooks/x` for webhook deliveries
- [ ] Implement `GET /health`
- [ ] Implement `GET /version`
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
- [ ] Implement signature verification
- [ ] Implement idempotent enqueue by `event_id`
- [ ] Implement trimmed event persistence
- [ ] Implement rejected request persistence

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
- [x] 429 does not consume an attempt
- [x] Queue cap = 5000
- [x] Queue overflow drops newest incoming job
- [x] Queue overflow is tracked with counters only
- [ ] Implement worker loop
- [ ] Implement transactional claim/update logic
- [ ] Implement retry scheduling
- [ ] Implement queue overflow counters
- [ ] Add scheduler tests

---

## 9. Startup recovery and health

- [x] Stale `processing` jobs older than 30 minutes reset to `queued` on startup
- [x] Recovery is logged to `dmguard.log` only
- [x] `/health` includes configured/ready/liveness and queue/error/drop counters
- [x] `/version` includes app + dependency versions
- [ ] Implement stale-processing recovery
- [ ] Implement `/health` aggregation
- [ ] Implement `/version`
- [ ] Add startup recovery tests

---

## 10. X API integration

- [x] DM lookup endpoint = `GET /2/dm_events/{event_id}`
- [x] Shared X API timeout = 10 seconds
- [x] Proactive token refresh
- [x] Token expiry metadata stored in SQLite
- [x] Refresh failure marks system misconfigured
- [x] Implement secret loader
- [x] Implement X API client
- [ ] Implement DM lookup DTO parsing
- [ ] Implement proactive refresh
- [ ] Add tests for request construction and parsing

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
- [ ] Implement attachment dispatch
- [ ] Implement authenticated media download
- [ ] Implement temp file lifecycle
- [ ] Implement frame extraction
- [ ] Add media pipeline tests

---

## 12. Classifier subsystem

- [x] Classifier runs as on-demand child process
- [x] IPC = temp JSON input file + JSON stdout
- [x] Single total timeout = 180 seconds
- [x] Kill classifier on timeout
- [x] `selftest` supports image and video
- [x] `--force-safe` returns 0.01
- [x] `--force-unsafe` returns 0.99
- [x] `--force-unsafe` video metadata uses trigger frame/time
- [x] Classifier stderr is captured and written to `classifier.log`
- [x] Implement subprocess contract
- [x] Implement fake classifier mode for early tests
- [ ] Integrate real ShieldGemma inference
- [ ] Implement selftest CLI
- [x] Add classifier contract tests

---

## 13. Moderation engine

- [x] Unsafe if violence/gore yes-prob >= 0.90
- [x] Allowlist short-circuit happens before DM lookup
- [x] First safe media DM adds sender to `allowed_senders`
- [x] Allowlisted sender jobs are still recorded
- [x] Allowlisted sender jobs end with `status='skipped'`
- [x] `skipped` means allowlist skip only
- [x] Block success adds sender to `blocked_senders`
- [x] Block failure updates `block_failed_senders`
- [x] Fail-open posture for v0.1
- [ ] Implement moderation decision engine
- [ ] Implement sender-state transitions
- [ ] Implement allowlist fast path
- [ ] Implement block cooldown logic
- [ ] Add moderation flow tests

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
- [x] MVP behavior appends one final audit row per job
- [x] `moderation_audit` retention = 30 days
- [x] `moderation_audit` index = `created_at` only
- [ ] Implement `job_errors`
- [ ] Implement `moderation_audit`
- [ ] Write final audit row on terminal job outcome
- [ ] Add audit and error history tests

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
- [ ] Implement prune command/function
- [ ] Implement daily prune trigger
- [ ] Add pruning tests

---

## 16. Setup orchestration

- [x] Setup is rerunnable and stateful
- [x] `setup_state.json` is non-secret metadata only
- [x] `setup_state.json` stores latest run only
- [x] Setup tracks per-stage artifacts
- [x] Stage invalidation is automatic
- [x] `--verbose` explains invalidation/progress only
- [x] Rollback is best-effort
- [x] Rollback attempts = 3 with 1s, 5s, 10s
- [x] Continue even if rollback fails
- [x] Setup writes append-only `setup.log`
- [x] `setup.log` always redacts secrets
- [ ] Implement setup state machine
- [x] Implement stage invalidation
- [x] Implement verbose output
- [ ] Implement setup log writer
- [x] Add setup-state tests

---

## 17. Services and edge orchestration

- [x] Traefik is the canonical bundled edge
- [x] Traefik is managed as a separate Windows service
- [x] Service manager = Servy
- [x] `dmguard` is also managed by Servy
- [x] Traefik is installed/started before `dmguard`
- [x] `dmguard` only installs after TLS + public reachability succeed
- [ ] Generate Traefik service definition
- [ ] Generate `dmguard` service definition
- [ ] Implement service install/start/update logic
- [ ] Add service config generation tests

---

## 18. Setup flow implementation

- [x] User inputs come from prompts and flags, not a user-authored config file
- [x] `config.yaml` is installer-authored, runtime-read, non-secret config
- [x] Public HTTPS reachability is checked before webhook registration
- [x] Unsupported environment => setup fails
- [ ] Implement preflight stage
- [ ] Implement local config stage
- [ ] Implement X auth stage
- [ ] Implement DuckDNS stage
- [ ] Implement Traefik stage
- [ ] Implement TLS stage
- [ ] Implement public reachability stage
- [ ] Implement X webhook registration stage
- [ ] Implement model warmup stage
- [ ] Implement app service stage

---

## 19. Admin CLI

- [x] `dmguard.exe allowlist add --user-id <id>`
- [x] `dmguard.exe allowlist remove --user-id <id>`
- [x] `dmguard.exe blockstate remove --user-id <id>`
- [x] `selftest`
- [x] `readycheck`
- [ ] Implement allowlist add/remove
- [ ] Implement blockstate remove
- [ ] Implement selftest
- [ ] Implement readycheck
- [ ] Add CLI tests

---

## 20. Testing plan

### Unit / component
- [ ] Config parsing tests
- [ ] Path policy tests
- [ ] Schema bootstrap tests
- [ ] Repository tests
- [ ] Scheduler tests
- [ ] Retry/backoff tests
- [ ] Signature validation tests
- [ ] CRC tests
- [ ] Media pipeline tests
- [ ] Classifier contract tests
- [ ] Moderation decision tests
- [ ] Audit/prune tests
- [ ] Setup state tests

### Integration
- [ ] Valid webhook -> safe media -> allowlist
- [ ] Valid webhook -> unsafe media -> block
- [ ] Allowlisted sender -> skipped before DM lookup
- [ ] Text-only DM -> text_only_logged
- [ ] Classifier failure -> error
- [ ] Stale processing recovery after restart

### Manual environment validation
- [ ] DuckDNS resolves to current public IP
- [ ] Public 443 reachable from outside
- [ ] TLS-ALPN-01 certificate issued successfully
- [ ] Traefik proxies only `/webhooks/x`
- [ ] X webhook registration succeeds
- [ ] CRC succeeds
- [ ] Real DM media path works end-to-end

---

## 21. Known risks / non-goals

- [x] Public HTTPS on a Windows host is an accepted MVP risk
- [x] DM media fetch reliability is a known integration risk
- [x] Host-level Traefik exclusivity is an accepted MVP limitation
- [x] No attempt is made to synchronize local sender state with X truth
- [x] No GUI/admin UI in v0.1
- [x] No containerization in v0.1
