# Retrospective editorial safeguards and additive short reading

BRF-DEV-121 extends the explicit round-series replay. Public API, ERD and operational approval remain unchanged.

## Reprints and known earlier reports

`briefing_editorial_guard.py` assesses the already accepted groups, without modifying the team's extraction, grounding, group IDs or recordings. Earlier completed, source-bound observations and an acquired official release are a bounded history, not a global search index or a publication approval. Each history record retains its URL, body/span hash, exact quote, conservative availability bound and clock quality. Later historical collection does not establish contemporary availability.

Every candidate is checked against earlier matching reports and the event time stated in its own current quotes. A new article clock is insufficient. The independent assessment distinguishes `REPEAT`, `UNCERTAIN`, `DISTINCT_EVENT` and `MATERIAL_UPDATE`. The latter needs current exact delta evidence. A same-company different event is distinct; lack of a matching older document does not prove a world-first event. A known earlier announcement that cannot be compared to an acquired original is held conservatively. One correction is permitted for a completed response missing required delta evidence; the original receipt and unchanged frozen input are retained. Unknown requests are not replayed.

The derived archive retains its parent archive hash and all native provider recordings. The Java importer independently checks the editor's frozen current quotes, history bounds, recorded provider response, prompt hash, delta IDs and selection binding. `REPEAT`/`UNCERTAIN` cannot be selected. `DISTINCT_EVENT` means distinct within the available corpus, not guaranteed first publication worldwide.

## Selection and company completeness

For this guarded path, the structured output schema binds each issue ID to its own exact current evidence and supported companies. Current evidence shorter than 80 Unicode code points is excluded conservatively before selection: this is a development support-size heuristic, not a semantic sufficiency guarantee. Generated facts still require their own verification.

A model duplicate in the same selection is rejected separately, with raw index, issue ID and choice hash, while the first valid occurrence can continue. It cannot authorize another event or fabricated fact. The importer recomputes the duplicate rejection. Other invalid bindings still fail closed. Every accepted company with selected evidence must survive into companyLinks; an empty model list cannot drop a grounded ASML participant.

## Grounded company metadata

`--grounded-company-metadata` projects names only from accepted, supported, exact issue evidence, restricted by cutoff and identity quarantine. Query associations (`name` or `companyName`) are never promoted automatically. The original source files, hashes and tags remain unchanged. Market context declares `companyMetadataPolicy=accepted-issue-company-evidence-v1`, and the importer recomputes the per-document names from its validated archive. Company background lookup uses these names.

## Short reading over an explicit series

`briefing_company_reading.py` also accepts a series bundle carrying `marketEnrichment.seriesCompanyOutlooks`. It writes `seriesCompanyReading`, preserving the validated full company analysis byte for byte. Each company gets a newly written brief (70 characters), watch condition (50) and comparison/change (60), followed by independent source/full-analysis validation. The existing compact UI renders these fields; full reading remains available.

Series reading uses `pricePolicy=not_connected`: it does not acquire, fabricate or relabel prices. Existing market indicators remain a separate layer. The legacy presentation-plus-price path keeps its existing price binding rules.

All runs use separate output directories, immutable request/response/usage records and explicit per-task paid-call bounds. Only exact request identities can reuse completed AI results. Changes to selection/history/context require new downstream requests. Earlier results and failed attempts are retained for comparison.

## Company comparison contract v2

`briefing_series_company.py --prompt-version company-outlook-v2` binds the generation schema to the edition: morning `updated/unavailable`, evening `compared/unavailable`. The new generator and independent verifier both distinguish “a comparable prior same-company judgment was not supplied” from “the company was absent from all morning material.” The latter cannot be inferred. V1 prompt bytes and completed results remain intact; mixed preserved v1/new v2 rows are checked against each row's actual frozen prompt version.

The completed BRF-DEV-121 sample preserves its first company result and uses v2 only for the repaired evening result. Its first edition has no eligible selected issue and remains held. Market/company/mobile completion is not forced for an empty candidate population.
