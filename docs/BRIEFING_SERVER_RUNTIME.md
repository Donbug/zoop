# Common briefing server runtime

The dedicated runtime fills the common schedule's producer boundary. At 09:20 and 17:30 Asia/Seoul it reserves the same unique date/edition jobs as `CommonBriefingScheduler`, verifies the current native public graph and source authority, selects and independently verifies issues, generates and independently verifies company judgments, and publishes under the existing usage lease. It writes the immutable original and complete personal candidate pool in one transaction. Public `getBriefing` and `getBriefingItem` read that original and its preserved literal evidence through the existing grant and graph guards. The publisher validates the list and every item-detail DTO before committing. Missing title/publisher metadata is shown as the existing DTO’s empty string and never invented.

The core producer alone expects current-window sources and an existing published native graph. The finite `--slot` entrypoint described below prepares new sources and permits a strictly additive native publication before running that producer. Historical imports alone do not establish current news coverage. Missing input becomes a failed `prepare` attempt with zero AI executions after a 30-minute input grace period; the queue then requires operator recovery. It never creates a current “no news” publication from absent current-window evidence. A newly activated graph after the cutoff cannot silently replace the cutoff's input.

## Build and start

```sh
docker build -f api/Dockerfile -t zoop-api:briefing api
docker build -f deployment/briefing/Dockerfile --build-arg API_IMAGE=zoop-api:briefing -t zoop-briefing:runtime .
docker run --rm zoop-briefing:runtime --check
```

The `api-container` required CI job builds both images and runs the credential-free entrypoint check. The entrypoint requires `BRIEFING_SERVER_ENABLED=true`; no environment or secret values are baked into the image. Run finite dedicated tasks with read-only root and writable private `/tmp`; leave the dedicated service at zero to prevent an extra continuous producer. Task user is 100:101. Do not replace or enable the shared AI reader's paid processing to run this producer.

| Runtime variable | Required meaning |
| --- | --- |
| `DB_URL`, `DB_USERNAME`, `DB_PASSWORD` | Existing application PostgreSQL schema; `DB_URL` uses JDBC PostgreSQL syntax. No migration or Spring bootstrap runs in this process. |
| `OPENAI_API_KEY` | Dedicated ECS Secret injection. The entrypoint moves it to a private 0600 ephemeral file and removes it from the child environment. |
| `BRIEFING_SERVER_AUTHORIZATION_REF` | Operator's separately recorded model budget authorization. Never reuse another generation session's balance. |
| `BRIEFING_SERVER_WORK_ROOT` | Dedicated durable 0700 briefing state directory. Use a separate EFS access point, not another producer's work directory. |
| `BRIEFING_USAGE_ARTIFACT_ROOT` | Shared application artifact root, read/write for append-only usage receipts and registered artifacts. |
| `ZOOP_DOCUMENT_READ_GRANTS` | Fresh operator-owned flat `zoop-ai-s1-1` grants. Requires `briefing-outlook`, `semantic-verification`, `openai`, read/store/quote-display/model-send. Configure the public API with this same grant path. |
| `ZOOP_DOCUMENT_READ_INGESTION_SOURCES` | Existing live native/legacy source authority routing. It remains independently enforced and is never replaced by a flat grant. |
| `BRIEFING_SERVER_SOURCE_SCOPE` | Additional explicit exact-document scope described below. The producer never infers model permission from quote-display permission. |

A private source scope file has this shape. IDs and hashes below are placeholders, not approvals or real data:

```json
{
  "schemaVersion": "briefing-model-scope-v1",
  "authorizationRef": "operator-authorization-reference",
  "sources": [{
    "sourceId": "approved-source",
    "documentId": "approved-document",
    "documentVersion": "approved-exact-version",
    "bodySha256": "64-lowercase-hex-digits"
  }]
}
```

Both the source scope and grants are re-read before each model dispatch and before publication. Recomputed input hashes cannot authorize forged quotes: the command rechecks the original graph, exclusions, article version, artifact digest, literal quote offsets, URL, publication window and company relation. A document outside the exact scope is excluded even when a source-wide flat grant exists. Register grants/scopes as new files after reviewing permission; do not overwrite another owner's native policy.

## Budget and receipt semantics

The core briefing model is fixed to `gpt-6-luna`, text only, no tools and the default service tier. Native source processing additionally uses the pinned independent Jev verifier described below. Limits are 16 reserved physical requests / US$1 conservative upper estimate per round and US$2 per **execution day in KST**, including historical work and prior unresolved reservations. Reservation is durable before dispatch. Rights and budget admission precede `model_start`, so refused dispatches never appear as live calls. A missing response holds its reservation and is never resent automatically.

The upper estimate uses US$0.50 input / US$1.50 output per million tokens with a conservative input envelope. This exceeds the [official standard Luna rates checked 2026-11-03](https://developers.openai.com/api/docs/models/gpt-6-luna); it is a spending guard, not an invoice. The usage ledger separately estimates known token receipts at the official standard US$0.10 / US$0.50 rates and records its price version and USD currency. `actual_cost` stays NULL without billing evidence. Other tiers and paid tools are rejected. Review the pinned rate basis before enabling a different model/tier.

`briefing_attempts` and `ai_executions` retain their existing PostgreSQL contracts. Features are `briefing` for selection and `briefing-outlook` for company analysis. Stage names are `selection`, `selection_verification`, `analysis`, `analysis_verification`; a changed repair and its verification share one retry unit. Replaying an identical recorded response is a local replay, not a physical retry. Raw prompts/responses remain in private runtime artifacts and are not copied into the usage ledger. Incomplete or unknown token counts remain NULL.

A PostgreSQL advisory lock excludes overlapping replacement workers. Queue state advances to `completed` only after database digests and a complete pool bound to the publication digest verify. Following a crash, an already committed publication is recovered from this proof without dispatching a model again; other interrupted jobs require recovery. Published originals are immutable, and this worker never regenerates them in place. Source/grant changes and independently rejected selected issues prevent publication. A bounded repair can retain supported issues; zero supported selected issues is a held generation, never an empty-news success.

## Verification and rollout boundary

- `PYTHONPATH=scripts <locked Python> -m unittest discover -s scripts/tests -p 'test_briefing_*.py'`: existing Python briefing regressions and server budget/admission checks, no project key.
- `companyIntegrationTest --tests com.zoop.graph.importer.BriefingServerPostgresTest`: disposable schema, native importer/composer, actual Python/Java subprocesses and JDBC ledger, authored model replies, transactionally published morning/evening originals, actual Spring list/detail HTTP 200 and current-grant revocation 503, failed-quality repair accounting, and prepare-failure idempotency.
- Container `--check`: dependency and entrypoint check only; it does not prove database or provider access.

Before increasing a service from zero: verify the exact image digest and source commit, all required CI, dedicated budget scope, valid model-send grants and exact document scope, writable private state, cutoff-eligible active native graph, and absence of another producer. Then verify a real bounded run through ledger -> original/pool -> public HTTP -> browser. Queue presence, health UP, a synthetic run, or imported historical data alone is not proof that live briefing generation works.

Disable both dedicated EventBridge schedules and stop only the owned finite briefing task if necessary; keep the dedicated service at zero. Preserve its private state, receipts, unknown reservations and immutable originals. Do not restore a DB dump, rewrite Flyway history, flip the graph pointer, clear budgets or roll back another producer's service as part of this rollback.


## Current public source intake and finite scheduled tasks

The dedicated worker also supports `--slot morning|evening`. It collects a bounded official Korea portal subset, validates each article's KOGL1 text-only badge, and selects at most one catalogue-related document for native S2/S3 processing. Policy-news and press-release each use one listing page; collection is limited to 50 HTTP requests, 30 accepted documents, 60 MB and 300 seconds. Coverage remains partial. Images, attachments, third-party works and unlicensed newsroom text are excluded. Terminal/unknown source attempts are excluded from future automatic collection rather than silently retried.

A new prospective processing source file authorizes the exact selected native scope and the actual OpenAI/TypeSafe recipients. Acquisition grants and old owner registries are never rewritten. `zoop-source-authority-delegates-1` delegates to the current original authority root plus the new briefing authority set. Original route removals and revocations remain live; duplicated exact ownership or unreadable/nested delegates fail closed. Only the new authority directory is writable by this worker.

Source-model calls use real native ledgers and the shared content-free briefing usage ledger, linked to a preparation attempt of the same round. Native processing may consume at most 12 physical HTTP calls, leaving at least 4 calls for briefing generation and independent verification. Both stages together have the existing hard 16-call / conservative USD1 round cap and USD2 KST execution-day cap. Standard Luna and pinned Jev are the only native destinations; no fallback provider is enabled. Jev input reservations conservatively account for repeated shared state per question. Missing transmission and usage stay NULL; unknown calls retain reservations and are never resent. Actual invoice cost stays NULL. Estimates identify USD and the pricing basis.

Native records are imported with the existing current-authority CLI, document registration, handoff importer and cumulative composer. The `BRIEFING_SERVER_ADDITIVE_GRAPH_ALLOWED=true` opt-in can publish a strict addition only: every existing issue, company, relation, article and evidence value must remain present and unchanged, the expected active version is checked under the shared publication lock, and normal exclusion carry/evidence/current-grant activation checks still run. It never approves a HOLD or selects conflicting fields. The general graph-round preparation/command settings and manual review queue remain unchanged.

For day-only publisher dates, `publishedAt` remains NULL and `publishedDate` remains the original day. `availableAt` is the native first-observed timestamp, explicitly marked `eligibilityBasis=first_observed`, and is checked against the immutable article version before sending or publishing. Detail limitations explain that observation is not publication. Native document versions are retained in the personal pool rather than replaced with a legacy SHA label.

Initialize only the new authority files with `--initialize-authority` before pointing the API to them. Use `/mnt/zoop-artifacts/briefing_server_authority/serving-delegates.json` for `ZOOP_DOCUMENT_READ_INGESTION_SOURCES`, `.../grants.json` for `ZOOP_DOCUMENT_READ_GRANTS`, and `.../model-scope.json` for `BRIEFING_SERVER_SOURCE_SCOPE`. Original authority leaves remain under the existing read-only mount.

Production scheduling should start finite ECS tasks before each cutoff (09:00 for the 09:20 KST morning cutoff; 17:00 for the 17:30 cutoff), with a 45-minute process limit. Each task exits after publication or a held/failed attempt. A duplicate delivery does not create another model call or overwrite a published round. Failed/unknown slots require explicit reconciliation; scheduler retries must be disabled. The first after-hours deployment check may specify `--slot evening --cutoff <actual-future-offset-time>`; this is marked as an initial delayed publication, with the real window and generation/publication clocks, never backdated to 17:30.

The API and dedicated briefing image are separate deployment components. GitHub's API/AI deployment workflows are manual `workflow_dispatch`; pushing a PR does not enable the worker, install source authority, import data or create its schedule.
