---
title: Issue 91 company detail and chart
status: implemented
created: 2026-10-14
owner: 박주형
tags: [web, company]
---

# WBS 6.7.8 · FS038/039/040/041/044

Extend existing D-COM-01/01b shell; inspected wireframe board04 and individual screens. PR worktree is based on main d35e303. User authorizes commit/push/PR; merges belong to the team lead. Company styles use Tailwind utilities and PR169 tokens.

Independent overview/quote/portfolio/chart/timeline/asOf graph/financials/documents regions. Public access never requests portfolio without verified member; clear private data immediately on owner/revision changes. Respect connected state and mock/valuation times, nullable money/currency and 0..1 weights.

Period 1d/1w/1m/1y with fixed 5m/1h/1d/1wk resolution; no resampling. Default 1m and supplied latest timestamp. Quote never gets historical asOf/graphVersion. Pin graph version/asOf across event/document/detail/graph/impact requests. Consume cursor pages without mixing snapshots. Unknown or date-only event times are never fabricated into exact historical instants; price points and approved datetime events can change asOf.

Bucket counts use period resolution; select bucket then individual issue. Prices overlapping events do not prove causation. URL stores company/period/asOf/version/tab/event/bucket/depth. Map return link restores full detail URL, historical graph bypasses development mock, highlights only existing nonderived graph edges backed by matching impact API steps; no invented industry/product paths.

Company metadata/profile, financials and source times are displayed without invented values. News/disclosure area consumes summary/link only, no copied paid source body. Independent retries, missing data vs errors, partial/version warnings. No unrelated stocks/document/AI workflows or backend producers.

Validate fixture flows, authentication privacy and late responses, periods/buckets/asOf/version, safe links and exact restoration, existing tests/lint/format/build plus desktop/mobile browser checks. Producer E2E and unconfirmed financial/calendar policy remain documented boundaries.
