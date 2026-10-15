---
title: Issue 11 initial watchlist
status: implemented
created: 2026-10-14
owner: 박주형
tags: [web, onboarding]
---

# D-WAT-01 / D-WAT-01b · WBS 6.4.5 · Issue #11

Implement explicit search, unique selection and removable chips, session-owned draft and query retention across steps, zero/holding empty copy, failed lookup/save recovery, and saving guards. No recommendations, pagination, generic request changes or error-code taxonomy.

References: docs/wireframe/README.md + manifest D-WAT-01; 01-auth-onboarding board and D-WAT-01 screenshot; user's outputs/wireframes-2026-10-12 D-WAT SVGs. Issue #11 overrides recommended-list examples: search at top, results, selected chips below.

GET /api/v1/companies, GET/PUT /api/v1/me/settings, GET /api/v1/portfolio use direct contract DTOs. Preserve settings version; save completed=true for zero selection too. Settings mode accepts assets/watchlist, NOT map all/personal. holdings present => assets, otherwise watchlist; navigation independently uses all only if holdings and watchlist both empty, otherwise personal. Previously saved investor/tutorial data stays unchanged unless draft supplies investor.

All completion, previous and selection controls plus shared step navigation are blocked during saving. Settings/portfolio lookup must succeed before completion. Async results never affect another session or an unmounted page. Validate screen states with Vitest, lint, format and build.

## Integration and verification · 2026-10-14

PR #23 merged at 774f87a, including review fix 3614592. Initial temporary PR d75ff1e patch was backed up and reversed before pulling main. HEAD is now 774f87a; only Issue #11 changes remained uncommitted at validation. No conflict entries, conflict markers or whitespace errors. User subsequently authorized commit/push to submit a PR; only the team lead may merge.

Full suite: 5 files / 34 tests passed (15 Issue #11 screen tests, 19 existing graph/router/smoke tests). Frozen install, lint, format and TypeScript/Vite build passed. Large map bundle warning remains upstream. Chromium controlled API verification: 1280px + 390px, no mobile horizontal overflow, search/select/save to /?mode=personal. No live backend/OAuth/E2E claim.

Session drafts prefer authenticated member ID, retaining selection/query across token rotation for the same member. When no member identity is available, token identity provides conservative isolation. Generic call() is unchanged. Saved company IDs without a previously seen search result display as IDs; newly selected results display names.
