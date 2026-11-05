# Briefing market capture (D-BRF-01/02)

The automatic native chain collects KOSPI/KOSDAQ daily index history and the
bank USD/KRW reference after source activation and before the slot cutoff. The
existing Yahoo/Naver transports are reused; no AI request is added.

`scripts/briefing_live_market.py` stores an immutable capture under the private
worker directory `market/<round-id>/capture.json`, with exact provider URLs,
HTTP receipt times, raw SHA-256 references, source rows and the round cutoff.
Publication rechecks those saved bytes without another HTTP request and copies
the indicators into `published_payload.marketVariables`. Its private proof is
stored in `public_snapshot.marketCapture`; the query DTO exposes only the usual
indicators. The current AI prose does not consume this new display-only input.

- Morning uses the latest completed daily index record; today's running daily
  candle is excluded. Today's close requires a matching provider session end
  before both collection and cutoff, including delayed sessions.
- Missing trading records carry the actual previous date and comparison, not a
  fabricated zero return. This is not a verified holiday/session calendar.
- A bank reference is `reference`, never an FX market close. A same-day bank
  value is an observation proved by its HTTP receipt, not a claim of a final fix.
- Failed indicators retain null values and their reason. Provider failure does
  not withhold a verified news briefing. Late or altered captures cannot become
  an on-time publication input. Publication never fetches missing receipts.

Saved personal deliveries remain immutable. `withRoundMarket` projects a missing
personal market section from the public response only when publication state,
round ID, date, edition, scheduled time, cutoff and market reference agree, with
no corrections. An existing personal market snapshot always wins. It never
borrows another round's or today's live prices. Historical values fetched after
the cutoff remain labelled `사후 조회한 일별 값`, including compact reading.

The personal reader also accepts the server's exact reuse of independently
checked common analysis while preserving `common-impact-relative-v1` as the
real prompt version. It does not claim a separate personal AI call or remove
round/company/evidence validation.

Regression coverage: `test_briefing_live_market.py`, the authored-market extension
to `briefing_auto_chain_smoke.py` / `BriefingServerPostgresTest`, and
`personalMarket.test.tsx`, `personalPriority.test.tsx`, `scheduledPersonal.test.tsx`.
No old publication, settings, delivery, feedback, migration, model receipt or
budget record is rewritten. Existing published rounds without a capture remain
missing; this change does not backdate a later provider query.
