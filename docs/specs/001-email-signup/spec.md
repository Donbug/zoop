---
title: Issue 35 email signup and authenticated navigation
status: implemented
created: 2026-10-14
owner: 박주형
tags: [web, auth]
---

# FS003 / FS006 · WBS 6.2.7

D-AUT-02 signup, D-AUT-01 email entry, D-ONB-01 destination. References: wireframe README/manifest + 01-auth-onboarding board and screen images; docs/api/openapi.yaml; docs/development/signup-policy-2026-10-13.md.

Use approved dynamic term bodies/versions and page through all terms. Block unavailable required terms and empty term lists. Email trim/format/max254, required password (unchanged spaces), optional display name; detailed password/name policies remain server decisions, never copy unapproved 8-character prototype rules. Server decides email uniqueness. Consent versions reset on reload. Render legal text as text, never HTML.

201 signup issues a cookie member session. No fabricated/local token. Recheck GET /api/v1/auth/session; incomplete => onboarding, completed => successfully fetched holdings/interests determine all/personal. Failed/partial lists block navigation and permit confirmation-only retry; user confirmed retry-only on 2026-10-14, with no fallback map navigation. Never re-POST successful signup on recovery. Unknown request outcomes prompt session confirmation or login, not automatic duplicate signup.

Cookie CSRF and cookie-aware route/graph guards are necessary compatibility changes. 2026-10-14 review decision: cookie-only common call/ApiError; no Bearer, localStorage credentials or refresh. Retain PR159 start/social-authorize/guest entry and server logout, without implementing external OAuth callbacks or backend producers. Prevent double submit, unsafe return URLs, late unmounted response navigation and cross-session hydration.

Verify invalid fields, consent, failures/recovery, terms pages/body unavailability, cookie/session states, route destinations, loading locks, privacy/session changes, existing tests, lint/format/build and controlled browser interaction. Live signup/login API producers are not yet implemented in main; fixture evidence is not server E2E.
