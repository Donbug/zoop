# AI usage aggregation rules

Scope: #134 / FS068 / screen `A-ADM-04b` / `GET /api/v1/admin/ai-usage`.

This note makes the aggregation rules in ERD v6 §32 and the OpenAPI contract executable as a source map and a set of synthetic expected cases. It does not claim that every source writer is installed. Missing source data is reported as unavailable; it is never represented as a measured zero.

Tasks 2–5 expose the protected admin read route and aggregate `document_analyses`, `chat_jobs`, `briefing_attempts`, and `ai_executions` for the five supported features. `daily`, `members`, and prices remain outside these slices and stay null/unavailable.

## Window and units

- Capture one `asOf` instant per response. Select events with `started_at >= windowStart AND started_at <= asOf`; `all` has no lower bound. The exact window starts are `asOf - 24 hours`, `asOf - 7 days`, and `asOf - 30 days`.
- Requests are feature-level accepted work units. Model calls are individual external provider attempts. A request may have zero, one, or several model calls.
- `execution_mode=live` is eligible for model-call/token/cost aggregation. `replay` and `save_only` are not external model calls. Count replay only when a stored model result was actually reused.
- Attribute a usage row to the KST date of `ai_executions.started_at`. A run crossing midnight remains on its start date.
- `succeeded` and `failed` count only those terminal outcomes in the feature's request population. Pending/running, withheld, cancelled, and unknown outcomes are not silently assigned to either count. Thus `succeeded + failed` may be less than `requests`.

## Feature source map

| API feature | Request population | Model-call population | Success / failure source | Retry unit |
| --- | --- | --- | --- | --- |
| `chatbot` | Accepted `chat_jobs` rows; one row is one accepted chat turn/job. Re-delivery or status polling does not create a request. | All `ai_executions` with `feature='chatbot'`, including detached rows whose `chat_job_id` was nulled after conversation deletion. Count confirmed provider attempts per stage. | Terminal `chat_jobs` outcome. | Distinct attempts after the first whose attempt record says `modelCalled=true`, counted once even if that attempt invokes multiple stages. |
| `news-analysis` | `document_analyses` rows with `stage='summary'` and a request actually made; exclude `status='not_requested'`. | `ai_executions.feature='news-analysis'` for the analysis; includes summary and semantic-verification calls, each once. | Terminal analysis state: available is success, failed is failure; pending/withheld are neither. | Additional accepted analysis attempt after the first for the same article version and stage. |
| `document-sentiment` | `document_analyses` rows with `stage='sentiment'` and a request actually made; exclude `status='not_requested'`. | `ai_executions.feature='document-sentiment'` for the analysis. | Terminal analysis state: available is success, failed is failure; pending/withheld are neither. | Additional accepted analysis attempt after the first for the same article version and stage. |
| `briefing` | One `briefing_attempts` row with `purpose='generation'` per generation/reprocessing attempt. A new attempt is a new request unit. | `ai_executions.feature='briefing'` owned by that `briefing_attempt_id`; count confirmed live executions per stage. | `status='completed'` and `stages.outcome='available'` is success; failed is failure; withheld, cancelled, and unfinished are neither. Completion means the producer finished and does not itself prove publication. | Distinct non-null `retry_unit_id` values among live executions; a generation+verification repair remains one retry. |
| `briefing-outlook` | One request for each `briefing_attempts` row with `stages.outlook.requestedAt`; filter the window on that timestamp. Do not count attempts with no outlook request. | `ai_executions.feature='briefing-outlook'` owned by that attempt. | `stages.outlook.outcome` available is success, failed is failure; withheld/cancelled/pending are neither. | Distinct non-null `retry_unit_id` values among live executions. |

The `briefing` and `briefing-outlook` request populations overlap by design. Never sum their request counts to produce a total request count. Do not attribute one execution to both features.

## Measures and null rules

- `modelCalls`: number of confirmed external provider attempts. A call is confirmed by its provider receipt or another persisted, explicit sent outcome. A row merely inserted before dispatch does not prove the provider was called. Exclude an explicit not-sent outcome. If any in-window execution may have been sent but has no conclusive outcome/receipt, return `null` for the feature's call total and explain the uncertainty in `note`.
- `inputTokens` / `outputTokens`: sum the reported token values for confirmed calls. A reported zero is valid. If any confirmed call has an unknown token amount, return `null` for that token total; do not show a partial sum as the total. If an uncertain-send execution could have consumed tokens, return `null`.
- `latencyMs`: compute from the feature request's accepted/started time to its terminal time, not from the sum of model-stage durations. Exclude requests missing either timestamp and state the incomplete coverage in `note`. Return `null` when there are no eligible duration samples.
- Actual cost comes only from confirmed billing data. Estimated cost requires known token quantities, a documented model price, price effective time, and currency. Do not convert or add different currencies. Keep actual and estimated fields separate; unavailable amounts are `null`, never zero. If currencies conflict within a feature total, leave the affected total and currency unavailable and explain why.
- `recentErrors` contains sanitized failure codes from attempt and execution records; never include prompt, response, credentials, user content, or raw provider payloads.
- `requests=0` is valid only when that feature's source is available and the query found no rows. Every response retains the stable five feature rows. Each row has `availability` (`complete`, `partial`, `unavailable`) and `unavailableMetrics`; unavailable numeric values are null. The response has the same completeness fields, and daily/member aggregates identify unavailable paths explicitly. `recentErrors=[]` means no errors; `recentErrors=null` means its source is unavailable. Use HTTP 200 with partial known data when at least a response can be formed; reserve 503 for endpoint-level failures that prevent a valid response.
- Chat executions link to request retries with `(chat_job_id, attempt_no)` and persist `provider_send_state` (`sent`, `not_sent`, `unknown`). Existing rows with null send state are unresolved for exact call counts.
- Briefing request windows use `briefing_attempts.started_at`; outlook request windows use `stages.outlook.requestedAt`. Execution usage uses `ai_executions.started_at`, `transmission_confirmed`, and `retry_unit_id`. Do not count `briefing-outlook` executions as briefing executions.
- If a published round in the selected window has no recorded generation attempt, return briefing request/outcome/latency metrics as unavailable rather than interpreting the missing historical record as zero.

## Synthetic expected cases

| Case | Input facts in the selected window | Expected aggregation |
| --- | --- | --- |
| Accepted chatbot question, router and answer succeed | 1 `chat_jobs` request; 2 confirmed live executions with tokens | `requests=1`, `succeeded=1`, `failed=0`, `modelCalls=2`; token totals are the sum of the two receipts. |
| Same request is re-delivered/polled | Same job and same recorded executions; no new accepted job or provider receipt | Request, call, retry, token, and cost totals do not change. |
| One new domain retry invokes two stages | One logical chatbot request; attempts 1 and 2; three confirmed executions total | `requests=1`, `retries=1`, `modelCalls=3`. The second attempt is one retry, not two. |
| Provider explicitly refuses before sending | One failed stage with persisted explicit not-sent outcome and no usage receipt | It contributes no model call and no tokens. The request failure count follows the terminal request outcome. |
| Provider may have received a request, but receipt is missing | One live execution with unknown send outcome | Request remains in its request population; exact model-call and potentially affected token totals are `null`, with a note. Do not infer a free failure. |
| Result withheld after provider call | Confirmed call receipt, request ends withheld | Include the confirmed call, tokens, and any confirmed/estimated cost; do not increment succeeded or failed. |
| Analysis uses cached result | One new analysis request returns a stored result without a model call | Increment request and `replayCalls`; leave `modelCalls` and tokens unchanged. |
| Briefing generation also invokes outlook | One attempt with ordinary generation calls and an outlook call | Assign ordinary calls to `briefing` and outlook only to `briefing-outlook`; do not duplicate the outlook call. Request counts follow their distinct feature populations. |
| No rows, source is installed and query succeeds | Empty valid source result | Counts are zero; usage totals are zero only where the complete source confirms no calls. Costs remain `null` unless billing evidence confirms zero. |
| No briefing attempts in an installed source | Query succeeds and returns no `briefing_attempts` rows | Report zero requests and calls; costs remain null absent billing evidence. |
| Run crosses KST midnight | Start before midnight, finish after midnight | Attribute the entire execution and its eventual receipt to the KST date of `started_at`. |
| Two currencies appear in one feature window | Confirmed amounts in USD and KRW | Do not add them. Return unavailable combined amount/currency with a mixed-currency note. |

## Implementation gaps to preserve in downstream tasks

1. The recorded briefing producer is an explicit CLI path. The operations scheduler is not automatically connected, so `requests=0` means no recorded producer attempts in the queried source, not that no legacy/other-path briefing ran.
2. Existing publications and old receipts are deliberately not backfilled. Historical briefing windows before the producer was enabled are incomplete, and should be labeled accordingly by consumers if requested.
3. `ChatModelRecorder.start` persists `attempt_no`; request-level retries still come from `chat_jobs.attempts[]` (`n`, `status`, `modelCalled`). `modelCalled` means that an attempt reached at least one model call, not the number of stage calls within that attempt.
4. `ChatStageReply.Failure` send state is persisted as `sent`, `not_sent`, or `unknown`, and the recorder stores provider receipt fields when present. Legacy rows without a definitive send state or receipt remain uncertain; do not infer a call from `failed` alone.
5. `estimated_cost` is nullable in storage. Briefing estimates have an explicit per-call basis, but other features have no established pricing source. Do not invent a price schedule.

The first three gaps affect source readiness. Partial feature availability also needs an API and consumer contract change. `daily` and `members` are optional proposal fields in the current contract and are outside the FS068 core acceptance criteria for this task.
