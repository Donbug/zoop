---
title: Issue 92 company documents and evidence
status: implemented
created: 2026-10-14
owner: 박주형
tags: [web, company, evidence]
---

# WBS 6.7.9 · FS040 / FS041 / FS043 · D-COM-02

Review and publish from latest main899d916, with #91 PR173 merged. Preserve the old local folder; PR worktree is C:/Users/user/Documents/Codex/zoop-92-pr. Only #92 is included; #93~95 are separate local work. Use existing Tailwind configuration and PR169 tokens, no new CSS or inline style. User authorized a PR; no merge. D-COM-02 board04 and actual node663:14180 document screen inspected; older node658:7834 shows events so use the actual document screen plus FS043 behavior.

Consume public listCompanyDocuments/getEvidence with companyId context and same asOf/graphVersion. All cursor pages use the same snapshot; failed/partial responses never become empty-success. Provide news/disclosure/all filter, selected-event scope, distinct documents-per-event counts, document source/time/title/relationship description, source links or exact missing-link notice. Quotes are supplied evidence excerpts, not downloaded article bodies.

Select document and evidence using URL fields, preserve existing period/asOf/tab/event/bucket while switching views or returning from graph. Clear selections on company change. Late company/selection/asOf responses cannot flash older evidence. Evidence identity/article/event/publication and list/evidence snapshot consistency checks and company-context sentiment guard prevent cross-context display. No future publication past selected cutoff. Display unavailable/withheld analysis distinctly; never invoke an AI provider or treat synthetic analysis as actual.

Independent list/evidence loading, missing metadata, empty, permission/unpublished, server error, retry and version unavailable states. Closed URL parameters remain recoverable and never silently switch to latest. Keep existing FS040 period+chart and FS041 bucket behavior, add linked evidence navigation from event cards.

Validate list/filter/source links/counts/evidence states, snapshot/pagination, future/cross-context suppression, rapid selection changes, exact state restoration, inherited tests and build/lint/format plus browser desktop/mobile. Actual producer E2E and legal availability require backend readiness; no new contract or paid source calls.
