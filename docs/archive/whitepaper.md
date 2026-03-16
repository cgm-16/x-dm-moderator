# X DM Moderation Prototype v0.1 개발자 사양서

## Executive Summary

본 문서는 entity["company","X","social media platform"] DM(1:1) 수신 이벤트를 웹훅으로 받아 로컬에서 이미지·영상 콘텐츠를 분류하고, **폭력/유혈(violence & gore)** 정책에서 위험으로 판정되면 **발신자를 자동 차단(auto-block)** 하는 v0.1 프로토타입 사양을 개발자가 바로 구현할 수 있도록 정리한 것입니다. v0.1의 핵심은 “실제 환경에서 끝까지 돌아가는가”를 검증하는 것이므로, 실패 시 기본 동작은 **fail-open**(오류가 났다고 자동 차단하지 않음)으로 고정되어 있습니다.

엣지/네트워크는 entity["organization","Traefik Proxy","reverse proxy"] 가 Windows 호스트에서 443으로 TLS를 종료하고, 앱(dmguard)은 `127.0.0.1:8080` 루프백만 리슨하도록 설계되었습니다. entity["organization","Let's Encrypt","certificate authority"] 인증서는 Traefik의 ACME `tlsChallenge(TLS-ALPN-01)`만 사용하며, 이 방식은 **외부에서 443 포트로 Traefik에 도달 가능해야** 합니다. citeturn4view0 entity["organization","DuckDNS","dynamic dns service"] 는 공인 IP 변화 대응을 위해 사용되며, 토큰 기반 업데이트 API(OK/KO 응답 포함)를 사용합니다. citeturn7view0

런타임은 “웹훅 수신(빠른 200 OK) → DB 적재/잡 생성 → 단일 워커 처리” 구조입니다. X 웹훅은 HTTPS/공개 접근 가능/포트 미표기/10초 내 응답/CRC 지원이 요구되므로, 수신기는 외부 API 호출 없이 **즉시 저장 후 응답**하는 비동기 패턴이 전제입니다. citeturn1view0turn14view2 또한 POST 이벤트는 `x-twitter-webhooks-signature`로 서명 검증을 수행합니다(consumer secret + raw body HMAC-SHA256 → base64 → `sha256=` 접두). citeturn14view0

데이터 모델은 “현재 상태(state) / 오류(error) / 발신자 상태(sender-state) / 감사(audit)”를 분리합니다. 특히 `moderation_audit`는 **append-only**이며, v0.1은 JSON blob 없이 **작은 typed column**만 저장하고 30일 보존 후 정리됩니다(인덱스는 `created_at` 단일).  

미지정(unspecified)로 남아있는 핵심 구현 리스크는 (a) X DM 조회/미디어 다운로드/차단에 필요한 **정확한 X API 엔드포인트·권한·토큰 저장 방식**, (b) DM 미디어 URL/토큰 만료/다운로드 실패 등의 **실환경 신뢰성**입니다. 본 문서는 미지정 항목을 “unspecified”로 표기하여, v0.1 빌드를 막지 않되 추후 결정을 명확히 남깁니다.

---

## 제품 목표와 범위

### 제품 목표

- 1:1 DM 수신 이벤트를 X 웹훅으로 수신하고, 메시지에 **첨부된 미디어(사진/영상/GIF)** 만 대상으로 로컬 분류를 수행한다.
- 폭력/유혈 정책에서 LlavaGuard가 **`rating=Unsafe`** 및 카테고리 **O2**로 판정하면 발신자를 즉시 차단한다.
- 텍스트-only DM은 **로그만 남기고 분류/차단을 수행하지 않는다**.
- 시스템이 이미 “안전”으로 판정한 발신자는 이후 DM을 **영구적으로 스캔 스킵(allowlist)** 할 수 있어야 한다(자동 학습 + 최소 수동 CLI).

### In-scope

- 1:1 DM만 처리(그룹 DM 제외).
- 미래 이벤트만 처리(초기 설치 시 과거 백로그/리플레이 없음).
- 폭력/유혈 단일 정책(O2_violence_harm_cruelty), LlavaGuard 이진 판정.
- 사진 다중 첨부: 하나라도 위험이면 차단.
- 영상/GIF: 프레임 샘플링 후 하나라도 위험이면 차단.
- 발신자 상태 테이블(allow/blocked/block-failed) 관리.
- 감사 로그(`moderation_audit`) 및 오류 로그(`job_errors`) 기록.
- Windows 단일 호스트 + 단일 X 계정 + 단일 호스트네임.

### Out-of-scope

- 그룹 DM 처리(AAA 문서에서도 v2 1:1 메시지는 지원하지만 그룹 대화는 미지원으로 명시). citeturn11view0
- 텍스트 유해성 분류(텍스트-only는 log only).
- 사용자 GUI/웹 콘솔(관리 UI).
- X의 실제 차단/허용 상태와 “동기화”(로컬 DB는 캐시/이력).
- DNS-01, Cloudflare Tunnel 등 대체 인그레스/인증서 경로.
- 프로덕션 내구성(정확한 데이터 손실 방지·정합성·SLA) 보장.

---

## 아키텍처와 네트워크 엣지

### 컴포넌트 개요

- X Webhooks: 이벤트 전달(POST) + CRC 검증(GET).
- Traefik: 443 TLS 종료, 라우팅(Host+Path) 제한, ACME 발급/갱신.
- dmguard(앱): `/webhooks/x` 수신기 + 워커 + 로컬 DB + 로컬 분류기 실행.
- DuckDNS: DDNS 호스트네임 제공 및 IP 업데이트.
- entity["organization","Servy","windows service wrapper"]: Traefik과 dmguard를 Windows 서비스로 설치/관리(의존성, 로그, 재시작 정책 등 지원). citeturn7view3turn7view4

### X 웹훅 요구사항과 엔드포인트 제약

X 웹훅은 (a) HTTPS, (b) 인터넷에서 접근 가능한 공개 URL, (c) URL에 포트 명시 불가, (d) 10초 내 응답과 200 OK, (e) CRC GET 지원이 요구됩니다. citeturn1view0turn1view1 따라서 공개 URL은 반드시 표준 443으로 노출되어야 하며, `https://domain:5000/...` 형태는 실패합니다. citeturn1view0turn1view1

또한 X는 POST 이벤트에 `x-twitter-webhooks-signature`를 포함하며, 이는 raw body 기반 HMAC-SHA256 서명 검증으로 출처 검증이 가능합니다. citeturn1view0turn14view0

### Traefik 구성 원칙

Traefik은 **install(static) 설정**과 **routing(dynamic) 설정**을 구분하며, 라우팅 설정은 provider를 통해 공급되고 중단 없이 hot-reload 될 수 있습니다. citeturn13view0turn1view3 v0.1은 file provider를 사용하여 라우팅을 YAML 파일로 관리합니다. citeturn1view3turn8view0

- **install(static)**: entryPoint(443), ACME resolver, file provider 경로, 로그 설정 등.
- **routing(dynamic)**: `/webhooks/x` 라우터/서비스, (디버그 시) 대시보드 노출 라우터.

file provider는 `directory` + `watch=true`로 파일 변경을 감시하여 자동 적용할 수 있으며(기본 true), 파일 시스템 이벤트 기반 동작/제약이 문서화되어 있습니다. citeturn8view0

### ACME / TLS-ALPN-01 고정

Traefik의 ACME `tlsChallenge`는 **TLS-ALPN-01** 방식이며, 사용할 경우 **Let’s Encrypt가 443으로 Traefik에 도달 가능해야** 합니다. citeturn4view0 v0.1은 dnsChallenge/httpChallenge를 사용하지 않습니다.

### DuckDNS 업데이트

DuckDNS는 `https://www.duckdns.org/update?domains=...&token=...&ip=...` 형태의 HTTPS GET로 도메인 IP를 갱신하고, 정상/비정상 응답으로 `OK`/`KO`를 반환합니다. citeturn7view0

### Windows 파일 레이아웃

v0.1은 설치/런타임 데이터를 분리합니다.

- `C:\Program Files\XDMModerator\` : 실행 파일, 템플릿(읽기 전용에 준함)
- `C:\ProgramData\XDMModerator\` : 설정/DB/로그/ACME 상태 등 변경 데이터

Microsoft 문서에서 ProgramData는 Program Files와 달리 표준 사용자 데이터 저장에 사용할 수 있으며 관리자 권한이 필요하지 않다고 설명합니다. citeturn1view4

### 컴포넌트 상호작용 다이어그램

```mermaid
flowchart LR
  X[X Webhooks] -->|HTTPS POST/GET (CRC)| R[Traefik :443]
  R -->|HTTP proxy 127.0.0.1:8080| A[dmguard webhook receiver]
  A --> DB[(Local DB)]
  A -->|200 OK fast ack| X

  A --> W[dmguard worker]
  W --> DB
  W --> M[Media fetch (from X / CDN)\nunspecified endpoints/auth]
  W --> C[Local classifier\nLlavaGuard-based\nCUDA runtime]
  W --> B[Block sender via X API\nunspecified endpoints/auth]
  W --> DB

  D[DuckDNS updater] --> DDNS[DuckDNS]
  S[Servy Windows services] --> R
  S --> A
  S --> W
```

---

## 런타임 흐름과 작업 모델

### 웹훅 수신기 설계

- **경로**: `POST/GET /webhooks/x`
- **GET(CRC)**: 쿼리 `crc_token`을 메시지로, consumer secret을 키로 HMAC-SHA256 후 base64 인코딩 및 `sha256=` 접두를 붙여 `{"response_token": ...}` JSON을 반환해야 합니다. citeturn14view2  
  CRC는 등록 시점뿐 아니라 주기적으로 발생하며, 실패 시 웹훅이 invalid 처리되어 이벤트 수신이 중단될 수 있습니다. citeturn1view1
- **POST(이벤트 전달)**: `x-twitter-webhooks-signature` 헤더를 위 문서 절차대로 검증합니다. citeturn14view0
- **응답 시간**: 10초 내 200 OK가 요구되므로, 수신기는 외부 호출(미디어 다운로드/분류/차단)을 수행하지 않고 “저장/큐잉 → 즉시 200”만 수행합니다. citeturn1view0

**요청 본문 크기 제한(Content-Length)**: v0.1에서 제한 값은 **unspecified**(구현 시 타당한 상한 설정 필요). Traefik에는 Content-Length 및 Request Path 관련 보안 섹션이 별도 존재하므로, 추후 정책화가 가능합니다. citeturn13view0

### 워커 및 잡 라이프사이클

- 워커는 **단일(순차 처리)** 이며 5초마다 poll.
- Runnable 조건: `status='queued' AND next_run_at <= now`
- 선택 순서: `next_run_at ASC, job_id ASC`
- 잡 상태(enum):
  - `queued`, `processing`, `done`, `error`, `skipped`(allowlist만)
- 스테이지(enum):
  - `fetch_dm` → `download_media` → `classify` → `block`
- `attempt`는 “현재 스테이지의 시도 횟수(0-base)”이며 스테이지가 전진하면 0으로 리셋.

### 재시도/백오프

- 일반 transient 실패: 최대 3회, 백오프 10s → 60s → 300s.
- HTTP 429(rate limit): **attempt를 소비하지 않으며**, reset 시간을 존중해 `next_run_at`을 설정한다. (헤더/필드명은 **unspecified**)

### 큐 정책

- 최대 큐(대기 잡) 수: 5000
- 가득 찬 경우: 신규 유입은 **드롭(가장 최근)** 하되 웹훅 응답은 성공(200)을 유지. 드롭 카운터는 기록(카운터명은 **unspecified**).

### stale recovery

- 앱 시작 시 `processing` 상태가 30분 이상 정체된 잡은 `queued`로 되돌리고 동일 스테이지/attempt로 재시도한다.
- 30분 판단에 사용하는 타임스탬프 컬럼명은 **unspecified**(DDL 예시에서는 `processing_started_at` 또는 `updated_at` 제안).

### 미디어 처리 규칙

- **첨부 미디어만** 처리(텍스트 내 임의 URL 이미지는 무시).
- 이미지 다중 첨부: 하나라도 위험이면 차단.
- 영상/GIF 프레임 샘플링:
  - 1 fps
  - t=1s부터 시작
  - 최대 12s까지(실제 길이로 clamp)
  - 하나라도 위험이면 차단
- 영상/GIF 크기 상한: 25MB
  - 초과 시 preview 이미지가 있으면 preview로 대체 분류
  - 없으면 잡 `error`
- 지원 불명/미지정 첨부 타입: **로그 후 무시**

### 잡 라이프사이클 타임라인 플로우차트

```mermaid
flowchart TD
  IN[Webhook POST received] --> V{Signature valid?}
  V -- no --> RR[Insert rejected_requests] --> ACK1[HTTP 200 (or 4xx)\nunspecified policy]
  V -- yes --> WE[Insert webhook_events]
  WE --> JNEW[Insert jobs: status=queued\nstage=fetch_dm\nattempt=0\nnext_run_at=now]
  JNEW --> ACK2[HTTP 200 OK fast]

  subgraph Worker Loop
    QSEL[Select runnable job\nqueued & next_run_at<=now] --> LOCK[Set status=processing\n(set processing_started_at)]
    LOCK --> STAGE{stage}
    STAGE -->|fetch_dm| FDM[Fetch DM details\nunspecified X API]
    STAGE -->|download_media| DLM[Download media\nsize caps + preview]
    STAGE -->|classify| CLS[Run local classifier\npolicy=O2_violence_harm_cruelty]
    STAGE -->|block| BLK[Call block API\nunspecified X API]
  end

  FDM --> OKFDM{success?}
  DLM --> OKDLM{success?}
  CLS --> OKCLS{success?}
  BLK --> OKBLK{success?}

  OKFDM -- no --> RETRY1[Update job: status=queued\nnext_run_at=backoff\nattempt++\n(or 429: attempt no++)]
  OKDLM -- no --> RETRY1
  OKCLS -- no --> RETRY1
  OKBLK -- no --> ERR1[Set job=error\nInsert job_errors\nUpdate block_failed_senders\n(cooldown 24h)]

  OKFDM -- yes --> ADV1[Advance stage=download_media\nattempt=0]
  ADV1 --> DLM
  OKDLM -- yes --> ADV2[Advance stage=classify\nattempt=0]
  ADV2 --> CLS

  OKCLS -- yes --> DEC{Safe?}
  DEC -- yes --> SAFE1[Update allowed_senders (auto)\nInsert moderation_audit outcome=safe\nSet job=done]
  DEC -- no --> ADV3[Advance stage=block\nattempt=0]
  ADV3 --> BLK

  OKBLK -- yes --> BLKD[Update blocked_senders\nInsert moderation_audit outcome=blocked\nSet job=done]

  ALW{Sender in allowed_senders?} -->|yes| SKIP[Insert moderation_audit outcome=skipped_allowlist\nSet job=skipped]
  IN -. allowlist fast path (if sender known) .-> ALW
```

---

## 데이터 모델과 SQL DDL

### 데이터 철학

- **DB는 X의 “진실”을 복제하지 않는다.** 로컬 DB는 시스템이 관찰/시도/결정한 **캐시 및 이력**이다.
- 상태(state)와 이력(audit), 오류(error)를 분리한다.
- 감사 로그는 append-only이며, v0.1은 작은 typed column만 저장한다.

### 스키마 비교 표

| 테이블 | 범주 | 목적 | 변경 특성 | 보존/정리 |
|---|---|---|---|---|
| `webhook_events` | 이벤트 원본 | 웹훅 이벤트 수신 기록 및 잡의 근거 데이터 | append-only | 30일(terminal job 정리 후 연쇄 정리) |
| `jobs` | 실행 상태 | 워커 스케줄링/재시도/상태기계 | mutable | 30일(terminal만) |
| `job_errors` | 오류 이력 | 잡 실패 원인 기록(오류 전용) | append-only | 30일(먼저 정리) |
| `rejected_requests` | 보안 이력 | 서명 불일치/형식 오류 등 거부된 요청 기록 | append-only | 30일 |
| `allowed_senders` | 발신자 상태 | “안전으로 판정된 발신자” 로컬 allowlist | mutable(수동 remove) | 자동 정리 없음 |
| `blocked_senders` | 발신자 상태 | “차단 성공했던 발신자” 로컬 기록 | mutable(수동 remove) | 자동 정리 없음 |
| `block_failed_senders` | 발신자 상태 | 차단 실패·쿨다운/재시도 대상 | mutable | 자동 정리 없음 |
| `moderation_audit` | 감사 | 최종(또는 다중) 판정/행동 로그 | append-only | 30일 |

### 테이블별 상세 스키마

아래에서 **(확정)** 은 본 대화에서 결정된 항목, **(unspecified)** 는 대화에서 명시되지 않은 항목입니다. DDL 예시는 SQLite 계열 문법을 기준으로 하되, **DB 엔진 자체는 unspecified** 입니다.

#### webhook_events

- 핵심 키: `event_id` (확정; 잡과 1:1 매핑의 기준)

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `event_id` | `TEXT` | `PRIMARY KEY` | (확정) |
| `received_at` | `TEXT` | `NOT NULL` | (unspecified; 30일 정리 기준 필요) |
| `payload_json` | `TEXT` | `NOT NULL` | (unspecified; 원문 저장 여부/형식 미지정) |
| `sender_id` | `TEXT` |  | (unspecified; allowlist fast path 최적화용) |

인덱스: (unspecified; 예시에서는 `received_at` 권장)

#### jobs

- `jobs.event_id`는 `NOT NULL`, `UNIQUE`, 그리고 `webhook_events(event_id)`로 FK(확정).
- status/stage/attempt/next_run_at 기반 스케줄링(확정).

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `job_id` | `INTEGER` | `PRIMARY KEY` | (unspecified; UUID/정수 미지정) |
| `event_id` | `TEXT` | `NOT NULL UNIQUE` + FK | (확정) |
| `status` | `TEXT` | `NOT NULL` | enum: queued/processing/done/error/skipped (확정) |
| `stage` | `TEXT` | `NOT NULL` | enum: fetch_dm/download_media/classify/block (확정) |
| `attempt` | `INTEGER` | `NOT NULL` | (확정; 스테이지 단위 리셋) |
| `next_run_at` | `TEXT` | `NOT NULL` | (확정) |
| `processing_started_at` | `TEXT` |  | (unspecified; stale recovery에 필요) |
| `created_at` | `TEXT` | `NOT NULL` | (unspecified; 30일 정리 기준) |
| `updated_at` | `TEXT` | `NOT NULL` | (unspecified) |
| `sender_id` | `TEXT` |  | (unspecified) |

인덱스: (확정) `UNIQUE(event_id)`; (unspecified) `INDEX(next_run_at, job_id)` 권장

#### job_errors

오류 전용 테이블(확정). 컬럼 구성은 대화에서 미지정이므로 최소 스켈레톤만 확정하고 나머지는 unspecified로 둔다.

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY` | (unspecified) |
| `job_id` | `INTEGER` |  | (unspecified; FK 여부 미지정) |
| `stage` | `TEXT` |  | (unspecified) |
| `attempt` | `INTEGER` |  | (unspecified) |
| `error_type` | `TEXT` |  | (unspecified) |
| `error_message` | `TEXT` |  | (unspecified; 민감정보 마스킹 필요) |
| `http_status` | `INTEGER` |  | (unspecified) |
| `created_at` | `TEXT` | `NOT NULL` | (unspecified; 30일 정리 기준) |

#### rejected_requests

거부된 요청(서명 실패/형식 오류 등) 기록(존재 확정). 컬럼 구성은 **unspecified**.

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY` | (unspecified) |
| `received_at` | `TEXT` | `NOT NULL` | (unspecified) |
| `remote_ip` | `TEXT` |  | (unspecified) |
| `path` | `TEXT` |  | (unspecified) |
| `reason` | `TEXT` | `NOT NULL` | (unspecified) |
| `body_sha256` | `TEXT` |  | (unspecified) |

#### allowed_senders

(확정) 컬럼 집합이 명시됨.

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `sender_id` | `TEXT` | `PRIMARY KEY` | (확정) |
| `created_at` | `TEXT` | `NOT NULL` | (확정) |
| `source_event_id` | `TEXT` | `NOT NULL` | (확정) |

#### blocked_senders

존재/역할은 확정, 컬럼은 **unspecified**.

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `sender_id` | `TEXT` | `PRIMARY KEY` | (unspecified) |
| `created_at` | `TEXT` | `NOT NULL` | (unspecified) |
| `source_event_id` | `TEXT` |  | (unspecified) |

#### block_failed_senders

존재/역할은 확정(24h 쿨다운 재시도 규칙 포함), 컬럼은 **부분 unspecified**.

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `sender_id` | `TEXT` | `PRIMARY KEY` | (unspecified) |
| `first_failed_at` | `TEXT` | `NOT NULL` | (unspecified) |
| `last_failed_at` | `TEXT` | `NOT NULL` | (unspecified) |
| `next_retry_at` | `TEXT` | `NOT NULL` | (unspecified; 24h 룰 반영) |
| `fail_count` | `INTEGER` | `NOT NULL` | (unspecified) |

#### moderation_audit

(확정) JSON blob 없이 typed column만 저장, `job_id` FK 없음(확정), `created_at` 단일 인덱스(확정), 30일 보존(확정).

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY` | (unspecified; 정수/UUID 미지정) |
| `job_id` | `INTEGER` | `NOT NULL` | (확정; FK 없음) |
| `event_id` | `TEXT` | `NOT NULL` | (확정) |
| `sender_id` | `TEXT` | `NOT NULL` | (확정) |
| `outcome` | `TEXT` | `NOT NULL` | enum: safe/blocked/skipped_allowlist/text_only_logged/error (확정) |
| `policy` | `TEXT` | `NOT NULL` | (확정; v0.1은 O2_violence_harm_cruelty 고정) |
| `category_code` | `TEXT` |  | (확정; LlavaGuard 카테고리 코드) |
| `rationale` | `TEXT` |  | (확정; LlavaGuard 판정 근거) |
| `trigger_frame_index` | `INTEGER` |  | (확정; 영상/GIF 트리거 프레임) |
| `trigger_time_sec` | `REAL` |  | (확정) |
| `block_attempted` | `INTEGER` | `NOT NULL` | (확정; 0/1) |
| `created_at` | `TEXT` | `NOT NULL` | (확정) |

### 인덱스 목록 표

| 테이블 | 인덱스 | 컬럼 | 유니크 | 상태 |
|---|---|---|---|---|
| `jobs` | `uq_jobs_event_id` | `(event_id)` | Yes | 확정 |
| `moderation_audit` | `idx_moderation_audit_created_at` | `(created_at)` | No | 확정 |
| `jobs` | `idx_jobs_next_run_at` | `(next_run_at, job_id)` | No | unspecified(권장) |
| `webhook_events` | `idx_webhook_events_received_at` | `(received_at)` | No | unspecified(권장) |
| `job_errors` | `idx_job_errors_job_id_created_at` | `(job_id, created_at)` | No | unspecified(권장) |
| `rejected_requests` | `idx_rejected_requests_received_at` | `(received_at)` | No | unspecified(권장) |

### 보존/정리 규칙

- 기본 보존 기간: 30일(확정)
- 정리 대상:
  - `jobs`: `done`/`error` 만 정리(확정), `queued`/`processing`은 정리 금지(확정)
  - `moderation_audit`, `rejected_requests`, `job_errors`, (필요 시) `webhook_events`: 30일 정리(확정)
- 정리 금지:
  - `allowed_senders`, `blocked_senders`, `block_failed_senders`는 자동 정리 없음(확정)
- 정리 순서(확정):
  1) `job_errors`  
  2) terminal `jobs`  
  3) 관련된 오래된 `webhook_events`  
  4) `moderation_audit`, `rejected_requests` 등 독립 이력  
  5) sender-state 테이블은 유지

### 샘플 SQL DDL

아래 DDL은 **예시**이며, (unspecified)로 표시된 컬럼/인덱스는 팀 합의에 따라 조정해야 합니다. 또한 `DATETIME` 대신 SQLite 호환을 위해 `TEXT`를 사용했습니다.

```sql
-- Sample DDL (engine: unspecified; SQLite-compatible style)
PRAGMA foreign_keys = ON;

-- webhook_events (event_id is required/decided; other columns are unspecified but often necessary)
CREATE TABLE IF NOT EXISTS webhook_events (
  event_id       TEXT PRIMARY KEY,
  received_at    TEXT NOT NULL,        -- unspecified (recommended)
  payload_json   TEXT NOT NULL,        -- unspecified (recommended)
  sender_id      TEXT                 -- unspecified
);

-- jobs (core scheduling columns decided; meta timestamps/ids partly unspecified)
CREATE TABLE IF NOT EXISTS jobs (
  job_id                INTEGER PRIMARY KEY AUTOINCREMENT,  -- job_id type unspecified
  event_id               TEXT NOT NULL UNIQUE,
  status                 TEXT NOT NULL,
  stage                  TEXT NOT NULL,
  attempt                INTEGER NOT NULL DEFAULT 0,
  next_run_at            TEXT NOT NULL,
  processing_started_at  TEXT,                               -- unspecified (stale recovery)
  created_at             TEXT NOT NULL DEFAULT (datetime('now')), -- unspecified naming
  updated_at             TEXT NOT NULL DEFAULT (datetime('now')), -- unspecified naming
  sender_id              TEXT,                               -- unspecified
  FOREIGN KEY (event_id) REFERENCES webhook_events(event_id) ON DELETE CASCADE,
  CHECK (status IN ('queued','processing','done','error','skipped')),
  CHECK (stage IN ('fetch_dm','download_media','classify','block'))
);

-- job_errors (error-only table; columns largely unspecified)
CREATE TABLE IF NOT EXISTS job_errors (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id        INTEGER NOT NULL,      -- FK 여부 unspecified
  stage         TEXT,
  attempt       INTEGER,
  error_type    TEXT,
  error_message TEXT,                  -- must be redacted
  http_status   INTEGER,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
  -- FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE   -- optional (unspecified)
);

-- rejected_requests (schema unspecified; minimal skeleton)
CREATE TABLE IF NOT EXISTS rejected_requests (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  received_at TEXT NOT NULL DEFAULT (datetime('now')),
  remote_ip   TEXT,
  path        TEXT,
  reason      TEXT NOT NULL,
  body_sha256 TEXT
);

-- allowed_senders (decided)
CREATE TABLE IF NOT EXISTS allowed_senders (
  sender_id       TEXT PRIMARY KEY,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  source_event_id TEXT NOT NULL
);

-- blocked_senders (schema unspecified; minimal)
CREATE TABLE IF NOT EXISTS blocked_senders (
  sender_id       TEXT PRIMARY KEY,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  source_event_id TEXT
);

-- block_failed_senders (cooldown semantics decided; columns unspecified)
CREATE TABLE IF NOT EXISTS block_failed_senders (
  sender_id       TEXT PRIMARY KEY,
  first_failed_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_failed_at  TEXT NOT NULL DEFAULT (datetime('now')),
  next_retry_at   TEXT NOT NULL,
  fail_count      INTEGER NOT NULL DEFAULT 1
);

-- moderation_audit (decided typed columns; no FK on job_id; index on created_at)
CREATE TABLE IF NOT EXISTS moderation_audit (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id              INTEGER NOT NULL,        -- no FK (decided)
  event_id            TEXT NOT NULL,
  sender_id           TEXT NOT NULL,
  outcome             TEXT NOT NULL,
  policy              TEXT NOT NULL,
  category_code       TEXT,
  rationale           TEXT,
  trigger_frame_index INTEGER,
  trigger_time_sec    REAL,
  block_attempted     INTEGER NOT NULL DEFAULT 0,
  created_at          TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK (outcome IN ('safe','blocked','skipped_allowlist','text_only_logged','error'))
);

-- Indexes (decided + recommended)
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_event_id
  ON jobs(event_id);

CREATE INDEX IF NOT EXISTS idx_moderation_audit_created_at
  ON moderation_audit(created_at);

-- Recommended (unspecified) indexes
CREATE INDEX IF NOT EXISTS idx_jobs_next_run_at
  ON jobs(next_run_at, job_id);

CREATE INDEX IF NOT EXISTS idx_webhook_events_received_at
  ON webhook_events(received_at);

CREATE INDEX IF NOT EXISTS idx_job_errors_job_id_created_at
  ON job_errors(job_id, created_at);

CREATE INDEX IF NOT EXISTS idx_rejected_requests_received_at
  ON rejected_requests(received_at);
```

---

## 보안·오류 처리·관측성

### 보안

- **TLS 종료는 Traefik에서만 수행**하고, dmguard는 루프백만 리슨한다.
- 공개 라우팅은 `Host(<duckdns-host>) && Path(/webhooks/x)`로 최소화한다.
- X 웹훅 보안은 CRC와 서명 검증을 모두 구현한다. CRC/응답 토큰 구성 및 서명 검증 절차는 X 문서에 명시되어 있다. citeturn14view2turn14view0
- Traefik 대시보드/API는 기본적으로 비활성화한다. Traefik 문서는 대시보드를 프로덕션에서 활성화/노출하는 것을 권장하지 않으며, 활성화 시에는 인증/권한과 내부망 제한을 권장한다. citeturn9view0
- 시크릿 취급:
  - `config.yaml`: 비밀이 아닌 런타임 설정(확정)
  - `secrets.bin`: 비밀값(consumer secret, 토큰 등) 저장(확정), 암호화 방식은 **unspecified**
  - 로그에는 토큰/시크릿/서명 원문/미디어 URL을 남기지 않는다(마스킹/해시).

### 오류 처리 전략

- v0.1은 **fail-open**:
  - DM 조회 실패 / 미디어 다운로드 실패 / 분류기 실패 / 차단 API 실패는 기본적으로 `job=error`로 끝나며, “불확실하니 차단”을 하지 않는다.
- block API 실패:
  - `block_failed_senders`에 기록하고 24시간 쿨다운 후 재시도(룰은 확정, 필드 구현은 일부 unspecified).
- 429 처리:
  - attempt 미소모 + reset 기반 `next_run_at` 재설정(헤더명/파싱은 unspecified).

### 관측성(로그·메트릭)

- Traefik 로그:
  - Traefik은 자체 로그(log)와 요청 로그(accessLog)를 분리해 제공하며, JSON 포맷과 헤더 redaction 등 구성이 가능하다. citeturn10view1turn10view2
- dmguard 로그(확정):
  - `dmguard.log`: 워커/잡 상태 전이, stale recovery, 주요 오류(민감정보 제거)
  - `setup.log`: 설치 단계 진행/실패/롤백 기록(민감정보 제거)
- 메트릭/카운터:
  - 필수 카운터 항목명은 **unspecified**이나, 운영상 최소로 다음을 권장: `webhook_received_total`, `webhook_rejected_total`, `jobs_created_total`, `jobs_dropped_queue_full_total`, `jobs_done_total`, `jobs_error_total`, `blocks_success_total`, `blocks_failed_total`, `allowlist_hits_total`.

---

## 설치·운영·CLI

### 설치/구성 흐름

- `configure.bat`가 사용자 입력을 받아 설정을 생성한다(입력 항목 자체는 상세 **unspecified**이나, DuckDNS 토큰/도메인 및 X 시크릿이 포함됨).
- DuckDNS 업데이트를 수행해 호스트네임이 공인 IP를 가리키도록 한다(OK/KO로 성공 판단 가능). citeturn7view0
- Traefik 설정은 템플릿 기반으로 생성:
  - `traefik-static.yml.tpl`
  - `routes-normal.yml.tpl`
  - `routes-debug.yml.tpl`
- 파일 교체는 atomic replace로 수행(구체 방식은 unspecified)하고, file provider `watch`에 의해 반영된다. citeturn8view0
- 서비스 설치/관리:
  - Servy로 Traefik과 dmguard를 각각 Windows 서비스로 구성하고, dmguard가 Traefik에 의존하도록 설정한다(Servy는 의존성/로그/헬스체크/재시작 등 기능을 제공). citeturn7view3turn7view4
  - Windows SCM 직접 제어가 필요할 경우 `sc.exe`로 서비스 등록/제어가 가능하나(v0.1의 표준 경로는 Servy), 명령 자체는 Microsoft 문서에 정리되어 있다. citeturn12view0turn12view1

### 디렉터리 배치

- Program Files: 실행 파일/템플릿(설치 산출물)
- ProgramData: 설정/DB/로그/ACME `acme.json`/temp 등 변경 데이터  
  ProgramData는 표준 사용자 데이터 저장에 활용 가능하다는 점이 문서화되어 있다. citeturn1view4

### 관리자 CLI(최소)

- `dmguard.exe allowlist add --user-id <id>`
- `dmguard.exe allowlist remove --user-id <id>`
- `dmguard.exe blockstate remove --user-id <id>`  
  (`blockstate remove`는 로컬의 `blocked_senders`와 `block_failed_senders`를 삭제한다. X에 실제 unblock을 호출하지 않는다.)

### 운영 전제/제약

- 공인 인터넷에서 **443 인바운드**가 Windows 호스트까지 포워딩되어야 함.
- X 웹훅 URL은 포트 지정 불가이므로 443 종단이 강제됨. citeturn1view0
- Traefik이 호스트의 443을 “독점”하는 모델(다른 서비스와 공존 고려는 v0.1 범위 밖).
- 단일 계정/단일 호스트/단일 호스트네임.

---

## 구현 계획과 테스트 계획

### 마일스톤 및 노력 추정

| 마일스톤 | 산출물 | 노력 |
|---|---|---|
| 인그레스/웹훅 MVP | `/webhooks/x` GET CRC + POST 서명 검증 + 200 OK fast ack + `rejected_requests` 기록 | 중 |
| Traefik 패키징 | static/dynamic 템플릿, file provider watch, Host+Path 라우트, ACME tlsChallenge 구성 | 중 |
| 잡/워커 코어 | `jobs` 상태기계, `next_run_at` 스케줄링, 재시도/429, 큐 상한/드롭 | 중 |
| 미디어 파이프라인 | 첨부 미디어 탐지, 다운로드, 25MB 제한, 영상/GIF 프레임 샘플링 | 중~상 |
| 분류기 통합 | LlavaGuard v1.2 0.5B 기반 inference 실행(CUDA), 이진 Safe/Unsafe 판정 로직 | 중 |
| 차단 액션 통합 | X 차단 API 호출(엔드포인트/권한은 unspecified), `blocked_senders`/`block_failed_senders` 업데이트 | 중~상 |
| 감사/오류/정리 | `moderation_audit` append-only 기록, `job_errors`, 30일 정리 + stale recovery | 중 |
| 설치 자동화 | `configure.bat`, `setup_state.json`, `secrets.bin`, Servy 서비스 등록/의존성 | 중 |

### 테스트 플랜

#### 단위 테스트(Unit)

- CRC 처리: `crc_token` → `response_token` 생성 규칙 일치. citeturn14view2
- 서명 검증: raw body 기반 HMAC-SHA256 base64 + `sha256=` 비교. citeturn14view0
- 잡 상태기계: stage 전이/attempt 리셋/terminal 상태 전이.
- 백오프: 10/60/300초 적용, attempt 상한.
- 429: attempt 미소모, `next_run_at` 산정(헤더 파싱은 mock; 헤더명은 unspecified).
- 프레임 샘플링: 1fps, 1s~12s clamp.

#### 통합 테스트(Integration)

- Traefik → dmguard 루프백 프록시:
  - Host+Path 매칭이 아닌 요청은 라우팅되지 않음(404/404 계열).
  - `/webhooks/x`만 dmguard에 도달.
- file provider watch:
  - `routes.yml` 교체 시 라우트 반영(파일 시스템 이벤트 기반). citeturn8view0
- DB 정리:
  - terminal 잡만 30일 기준 정리, `queued/processing` 보존.

#### 종단간 테스트(E2E)

- 실제 X 웹훅 등록/CRC 통과:
  - 공개 HTTPS, 포트 미표기 충족. citeturn1view0turn1view1
- DM 수신 → 안전 이미지:
  - allowlist 자동 등록(`allowed_senders`)
  - `moderation_audit outcome=safe`
- DM 수신 → 위험 이미지:
  - 차단 호출 시도 및 성공 시 `blocked_senders`
  - `moderation_audit outcome=blocked`
- 텍스트-only:
  - `moderation_audit outcome=text_only_logged`, 차단 없음

#### 수동 운영 테스트(현장 시나리오)

| 시나리오 | 절차 | 기대 결과 |
|---|---|---|
| 인그레스 실패(포트 포워딩 누락) | 443 미개방 상태에서 설치 진행 | ACME 발급 실패(프록시 도달 불가) 및 setup 실패. tlsChallenge는 443 도달이 필요. citeturn4view0 |
| CRC 실패 | CRC 응답 토큰 형식 오류 | 웹훅 invalid 처리 및 이벤트 수신 중단 가능. citeturn1view1turn14view2 |
| 미디어 다운로드 실패 | 네트워크 차단/URL 만료 | fail-open: job error, audit=error, 차단 없음 |
| 분류기 실패 | 모델 파일 누락/런타임 오류 | fail-open: job error, 차단 없음 |
| 큐 가득 참 | 5000개 초과 유입 | 신규 드롭 + 드롭 카운터 증가 + 웹훅 응답은 200 유지 |
| 서비스 재시작/정체 | 워커 강제 종료 후 재시작 | 30분 이상 processing 잡이 queued로 복구(stale recovery) |
