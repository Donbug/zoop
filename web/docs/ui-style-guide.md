# Shared detail panel styles

## Auth and onboarding header

Use `SlimHeader` from `@/components/common/SlimHeader` for D-AUT-01/02, D-ONB-01/02 and D-WAT-01/01b. It matches Figma 619:1087 using Tailwind zoop tokens and local icons. Keep `ServiceHeader` for the normal service navigation. Tutorial cards (D-GRP-T~T5) occupy their own left column rather than covering the map legend. D-GRP-07 reuses `panelStyles` for the two-company path rail; see `WIREFRAME_ALIGNMENT_20261017.md` for its snapshot-bound semantics.

Read before editing frontend UI. Baseline: D-GRP-03 company side panel, Figma 619:6729. Applies to D-GRP-02 event, D-GRP-04 relation, D-GRP-05 evidence. Wireframes remain the navigation reference; this guide unifies the visual primitives, not the data semantics.

## Import and reuse

```tsx
import { panelStyles as ui } from '@/components/common/detail-panel-styles';

<aside className={ui.shell}>
  <header className={ui.header}>
    <h2 className={ui.title}>연결선 상세</h2>
    <button className={ui.close} aria-label="상세 닫기">
      ×
    </button>
  </header>
  <div className={ui.scroll}>
    <section className={ui.section}>
      <h3>공유 사건</h3>
    </section>
  </div>
</aside>;
```

`shell`, `wideShell`, `header`, `title`, `close`, `scroll`, `sectionFrame`, `section`, `muted`, `secondary`, `itemTitle`, `button`, `actions`, `textActions`, `state`, `footer`, `avatar`, `list`, `badge` are complete, statically discoverable Tailwind class recipes. `sectionFrame` supplies the shared padding/border for specialized content such as company charts; `section` also supplies text and headings. `wideShell` is reserved for the 400 px D-GRP-05 evidence dialog. Use `actions` for bordered button grids and `textActions` for Figma's borderless evidence/document actions. Keep native HTML semantics and accessible labels in the calling component. Do not concatenate dynamic Tailwind class fragments.

## Tokens and proportions

For embedded Markdown such as D-AUT-02 terms, use `MarkdownContent` with
`headingOffset={1}` so document headings start below the page h1. The offset
changes heading semantics only, caps at h6, and preserves the existing visual
classes. Omit the prop for standalone documents to keep their original levels.

Tokens live in `src/index.css` under `@theme`. Use `font-panel`, `text-panel-ink`, `text-panel-muted`, `border-panel-line`, `border-panel-control`, `bg-panel-soft`, `rounded-panel` instead of repeating hex values. Error and warning text uses `text-zoop-alert`.

| Element               | Baseline                                |
| --------------------- | --------------------------------------- |
| Rail / section        | 320 px / 16 px padding; evidence 400 px |
| Font                  | Pretendard Variable                     |
| Heading               | 17 px / 25.5 px / bold                  |
| Section / list title  | 13 px / 12 px                           |
| Body label / action   | 11 px / 12 px                           |
| Border / radius       | 1 px `#d6d6d2` / 4 px                   |
| Close / action height | 32 px / 32 px                           |

These values come from the D-GRP-03/D-GRP-05 Figma frames (619:6729, 619:8225), including the 11 px body scale and 32 px controls. A future accessibility/responsive size change should update all panels together, not introduce one-off typography. Existing chart and graph geometry CSS stays local; new repeated UI styling belongs in these recipes. Avoid unlayered `font: inherit` or high-specificity rules overriding Tailwind utilities.

### Dark theme

`:root[data-theme='dark']` in `src/index.css` gives every `zoop-*` and `panel-*` token a dark value; light values stay in `@theme`. Use tokens instead of hex so both themes follow. The Tailwind `white` and `gray-*` scale is inverted in dark for screens not yet on tokens. G6 canvas colors cannot read CSS, so graph code calls `themeColor()` from `src/util/theme-color.ts`; the header moon button (`toggleTheme`) reloads so the canvas redraws. Black line icons from `/graph-assets` carry `data-icon` and are inverted in dark; company logos are not.

## Behavior checklist

- Heading focus on selection; visible keyboard focus; Escape closes; restore focus to the opener or map when it no longer exists.
- Independent scroll area, stable graph instance/zoom, URL selection and Back navigation preserved.
- Distinct loading, failure/retry, empty and permission states. Never fabricate missing evidence, dates or direct business relations.
- Evidence dialog blocks background interaction and returns to the selected panel; shared actions pass actual IDs, graph version and map URL.
- Verify D-GRP-02/03/04/05 after shared recipe changes. Tests are in `tests/graph` and `tests/evidence`.

## Published-result feedback

Import `FeedbackButtons` from `@/components/common/FeedbackButtons` for member-only result feedback. Supply the feature, stable target ID, immutable target version and the confirmed saved value. Pass `undefined` until the saved vote has been read successfully; never turn a failed read into `none`. Provide a retry action alongside a read error. Keep this component keyed by the current member/session and result identity so pending responses and optional dislike reasons cannot cross accounts.

The component uses existing Tailwind tokens, focus rings and native buttons with `aria-pressed`. It confirms the returned target/version/value before displaying a saved vote, preserves the last confirmed value on failure and retries the desired final state. A 409 (result version changed) asks for a refresh instead of offering retry, because resending the same version is rejected again. Results without a version (`graphVersion: null`) show a note instead of the buttons. Guest/checking sessions receive login/status guidance. See `PublishedBriefing` for paginated saved-vote reads and round/issue usage.

## Account menu

Use `AccountMenu` from `@/components/common/AccountMenu` through `ServiceHeader` for D-GRP-01/D-MY-01 and other service screens, including mobile. It replaces the member link to `/my` with a popup containing confirmed name/email and logout only; nonmembers retain the login link. This is the user's approved account-navigation refinement, rather than a new profile/settings page. Keep styles in Tailwind tokens.

Click/tap, Enter/Space and arrow keys open the menu, with `aria-expanded` reflecting its state. Focus the logout item when opening; Escape closes and returns focus to the trigger, and outside pointer/Tab/focus departure close it. Disabling a focused action can cause a native browser blur, so keep pending/error UI visible and restore retry focus. Logout reuses cookie/CSRF transport, preserves the session on failure, prevents duplicate requests and ignores old responses after a member change. D-MY-01's page body no longer owns logout. Cover these behaviors with `tests/auth/account-menu.test.tsx` and `tests/auth/authJourney.test.tsx`.

## Admin screen primitives (A-ADM-\*)

Admin screens (`/admin/*`) are dense operation tables, not detail panels. They share Tailwind recipes and small components instead of `panelStyles`:

```tsx
import {
  ErrorBox,
  Loading,
  PageHeader,
  Section,
  Segmented,
  Table,
} from '@/components/admin/common/AdminUi';
import { BUTTON, TD, TH, count } from '@/components/admin/common/adminStyles';
```

- `adminStyles.ts`: class recipes (`BUTTON`, `PRIMARY_BUTTON`, `TH`, `TD`, `LINK`, `SELECT`, `TEXTAREA`, `SEARCH_INPUT`, `FOCUS_RING`), `count`/`formatPercent`, and `adminErrorMessage`/`adminActionErrorMessage` for API failures.
- `AdminUi.tsx`: `PageHeader`, `Section` (title + links to other admin screens), `Table` (caption + horizontal scroll), `Segmented` (period/status filters, `aria-pressed`), `Tabs`, `Metric`, `Loading`, `ErrorBox` (retry), `Empty`, `Note`, `MoreButton` (opaque-cursor paging with `useCursorPages`).
- Colors use the `zoop-*` tokens in `src/index.css`; values match the `panel-*` tokens. Error text uses `text-zoop-alert`.
- Admin writes (reprocess, correction, suspension, member block/unblock) take a required reason, send the admin CSRF token and an `Idempotency-Key` from `useIdempotencyKey` (the same key when an unanswered request is resent unchanged, a new key after an edit or a definite 4xx rejection), and show the result inline.
- Unknown values from the API (`null`) render as `–`, never as `0`.

## Graph feature port

D-GRP-01/01b uses `graph-view` for member/mode-scoped state and legend keys. G6 supplies the conditional desktop minimap. Saved zoom/pan is reused only when the map size is unchanged; otherwise the default layout opens. `MapDetailSheet` owns M-GRP-01 modal snaps and focus return; `IsolatedIssuesPanel` reuses the detail panel tokens.

## Map appearance and graph filtering

D-GRP-01/01b MapPage provides the approved light/dark GraphAppearanceContext and applies `mapAppearanceStyles` from `@/components/common/map-appearance-styles`. Its shared `graphTypography` recipe layers map-specific readability over `panelStyles`, including D-GRP-02/03/04/05. Other service pages keep the existing panel baseline. MapDetailSheet passes the same recipe across its mobile portal boundary. Explicit appearance overrides support local comparisons; normal routes need none.

Render one GraphLegend group in the top toolbar using the GraphCanvas portal slot. Preserve its member/mode-scoped visibility state, aria-pressed, relationship explanations, camera, selection and at least one visible node kind. The left legend was removed by user request. Let toolbar items scroll horizontally without shrinking or creating vertical clipping.

Company logos use `CompanyLogo`, `logoScale` and `logoBackground` from the shared logo utility. Background marks with checked safe margins fill the circle; other symbols fit the inscribed square (68% diameter) and use object-contain. Preserve brand colors and the Micron/Amazon backgrounds across themes. See [graph UI improvements](GRAPH_UI_IMPROVEMENTS.md) for asset provenance, verification and scope.

D-GRP-01/01b uses `graph-readability` for screen-size text, LOD and measured label culling. Nodes are not draggable; dragging moves the map camera only. Mobile tools reuse zoop tokens and 44px targets. See [canvas enhancements](GRAPH_CANVAS_ENHANCEMENTS.md) for behavior and validation limits.

## Briefing at-a-glance reading (D-BRF-01/02)

`CompanyOutlooks` uses a native, keyboard-accessible disclosure per selected company in `reading=compact`. Show separately generated, independently verified `company.card` fields: topic (12 Unicode characters), event title (32), and complementary qualification (64). Do not clip text or use the longer `reading.brief` as a fallback. Do not hardcode particular companies, a positive interpretation, or exactly three companies: one issue may involve several companies.

Opening a company reveals its existing `CompanyPrice`, v2 fact/background/condition reading when provided, and the full `CompanyAnalysis` with the original evidence links. Analysis is already expanded within the company disclosure, so opening it does not require another click just to read the full analysis. `reading=full` retains the expanded full layout and all existing price/baseline, unavailable, cutoff and evidence behavior. Cards without the supported schema, a PASS result, all three roles, bounded complete text and same-company evidence show a short unavailable message and still permit access to the original analysis. Round identity/edition/cutoff guards remain required. Card statement evidence is available inside the disclosure. Full reading remains unchanged; the card is an optional independent layer, not a replacement reading version.

Only screen-specific composition changes; reuse `briefingStyles` and existing Tailwind tokens. Do not change shared graph panel styles, API fields or stored text to implement this presentation. Regression: `tests/briefing/companyOutlooks.test.tsx`.

## Briefing date and edition selection (D-BRF-01/02)

`BriefingRoundPicker` updates date and edition together. A date with one published edition selects it; when both are published, retain the current preference. A published edition takes priority over a suspended one for automatic selection, while suspended editions remain accessible for their suspension notice. The latest option resolves an edition on the newest history date. Preserve reading and personal-view query parameters. Explicit links to a missing edition remain inspectable with an absence notice; do not silently rewrite user-supplied links.

Use `listBriefingRounds` to distinguish published, suspended, absent, and unknown. Complete a date that crosses a cursor boundary before choosing or declaring absence. Disable absent editions and explain their missing publication history. History failure or unloaded pages mean unknown, not absent; keep manual date lookup and retries. A late page response must not override a newer date/edition navigation. Do not fetch new model/price data or alter stored publications for this control. Regression: `tests/briefing/briefingRounds.test.tsx`.

## Source-bound judgment update (D-BRF-01/02)

`JudgmentUpdate` precedes selection-membership comparisons when a validated `judgmentUpdate` snapshot exists. Show the current conclusion, then compact selected-company cards and a separate previous-company watch section. Expanded cards show the actual prior judgment, new evidence, reason and observable strengthen/weaken conditions. Never treat a different company's industry context as that company's prior forecast. Preserve the former full analysis under an explicitly labelled archive disclosure; prices, market summaries, references and date/edition selection remain available. Source context uses native disclosures and plain text; absent/withheld/mismatched updates keep the original company view. Editorial changes must say that automatic verification applies to the pre-edit model draft.

## AM focus and PM evaluation (D-BRF-01/02)

`EditionReview` is a source-bound editorial snapshot. AM leads with today's selected companies and observable conditions; previous companies remain in a separate continuation disclosure. PM leads with the market's actual observation range, then every company in the referenced morning snapshot, new core companies, and next-session conditional scenarios. Business-condition checks and price movement remain separate. Missing intermediate dates, stale index closes, missing intraday/sector/flow observations and absent morning results must never become a daily verdict, causal news story or forecast score. Keep all existing prices, sources, full analyses and edition selection accessible. Label editorial review separately from independently model-verified output.

D-BRF-01/02 기업 카드의 토스 가격 관측은 `companyPriceContext`의 동일 회차·검토 버전·마감·기업·근거를 확인한 경우만 제공합니다. 간단히는 가격 한 줄, 펼치면 하루 흐름·아침 이후·기사 전후 완료 봉과 관측 구간을 읽습니다. 기존 Yahoo 가격·원문·사업 판단을 유지하고 시장 전체 장중 미제공과 기업별 분봉 제공을 구분합니다.

D-BRF-01/02 optional `companyPriceContext.outlookIntegrationVersion` binds a price-aware outlook to the original business judgment/stance/evidence. Use its takeaway and outlook text in the actual company reading; keep calculation details collapsible and original publication prices accessible. Show percent change with its exact baseline date in the compact price row. `marketReference` displays dated KOSPI/KOSDAQ and FX references including source/delay; do not call a multi-day comparison a previous-day return, or domestic indices the benchmark for an overseas stock. Missing/mismatched integration falls back to the preserved business reading. Regressions: `editionReview.test.tsx`, `priceContext.test.tsx`.

## Issue-centered briefing (D-BRF-01/02, 2026-10-24)

The user-requested default reading supersedes the selected-company composition above for `/briefing` and `reading=compact`. `IssueCentricBriefing` presents dated market indicators, up to three selected **issues**, changes from the prior judgment, then watch conditions. `reading=full` preserves the existing analysis, tracked-company context, market summary, prices, evidence and selection comparisons. This is a composition change; stored results and selection policy are unchanged.

Use `eventId` as the card identity. Several issues can involve the same company and one issue can involve several companies. Expand a native issue disclosure for the existing issue summary, connected companies, business judgment, dated price observations and source evidence. Preserve original evidence retrieval and graph/feedback actions. Closed cards do not mount detailed evidence components. Keep publication limits and round feedback accessible in footer disclosures, with unexpected failures and feedback-read retry visible.

`briefingIssueViews` projects existing v5 company statements conservatively: the reviewed/model/price versions and cutoff must match; a statement must cite uniquely assigned evidence of this issue, cite only that company's reviewed sources and not cite another selected issue. Ambiguous shared evidence and cross-issue statements are withheld, not copied to each card. A displayed label describes an existing **company business judgment using the issue and cited background**, not an independently verified issue-only impact or share-price direction. Missing output stays missing. Referenced, nonselected background remains available in the company judgment sources. Do not infer causality from a dated price change.

SJY051's merged PRs #168/#266/#279 provide document/company sentiment, live analysis and verified issue/company impact handoff rows. The current public graph snapshot/API does not expose those impact labels; this UI does not claim that connection or manufacture S3 labels from document sentiment. See `api/docs/GRAPH_READ_HANDOFF.md` bundle -6/-7 and `docs/design/sentiment.md`. A future integration must bind issue/company/relation/graph version, current rights, verified quote effects and unavailable states without aggregating conflicting rows or presenting the producer's unverified proposal as verified reasoning.

Reuse `briefingStyles` and shared Tailwind tokens. Wireframe references: board `05-briefing`, D-BRF-01 node 620-948 and D-BRF-02 node 620-1278. The user's issue-first reading overrides the older company-first default while retaining the explicit full view. Regression coverage: `issueCentricBriefing.test.tsx`, `morningBriefing.test.tsx`, existing briefing/personalization/recap/round-selection tests.

## S3 source-bound issue impacts (D-BRF-01/02)

`BriefingS3Impacts` loads the selected issue's public `/briefings/{roundId}/items/{eventId}/impacts` endpoint only after the issue is expanded. Full reading provides the same data with `BriefingS3Disclosure`. Show distinct source rows, exact quote effects and original URLs per company; never aggregate conflicting source verdicts or reuse a document/company sentiment as an issue rating. Keep the existing v5 company analysis explicitly separate, with its stored prices and full view intact. Missing results, verified undetermined, withheld results and a transient fetch error are different states. Label replay/authored-test and synthetic inputs explicitly. Response identity/version/cutoff/company binding and unmount guards prevent a late result from another issue being shown. Reuse existing `briefingStyles`, native disclosures and safe original links. API/authority details: `api/docs/BRIEFING_S3_IMPACTS.md`; regression: `s3Impacts.test.tsx`.

Historical real-news reviews must show `reviewContext`, later generation time and preserved quote-context scope. Never label them as the original publication verdict. Generation without evidence citations is distinct from a Jev failure or an absence of news. Keep the old business analysis and stored prices separate; a page view must not generate a rating.

D-BRF-01/02 source facts and directional assessment are separate in `BriefingS3Impacts`. Render `facts` with the stored issue title, exact source-context disclosure, dated source and original link even when the assessment is undetermined or no-evidence. Never apply effect colors/labels to fact records, and never describe source-text matching as independent verification of a business effect. Preserve each Jev-assessed `evidence` span separately; broader fact context may include material outside that assessment. Historical context-expansion metadata identifies reused generation. Withheld rows must not expose facts. Existing lazy fetch, error/retry, original prices and full reading remain intact.

D-BRF-01/02 held assessments can expose a collapsed `evidencePlan` disclosure: existing source supplements, their scope and original links, then contemporaneous information gaps and future outcome checks. Label it as AI re-evaluation pending. Keep the verified label and actual effect citations above it. Do not turn a background article into the selected issue's cause or require future realised outcomes to exist at an earlier cutoff. Source/authority failure remains an error, not a fabricated empty plan. The compact main screen stays unchanged.

D-BRF-01/02 completed `supplementalReview` results lead within the expanded issue/company S3 panel with the latest label, previous→latest transition, explanation, confirmed source facts and native effect citations. Label the old assessment as previous verification; keep its facts/quotes, all prices and full reading. Separate a verified-but-undetermined effect from missing data. Source links remain accessible for held results. The Korean explanation is editorial; the underlying quote effects are independently Jev-verified. Later-collected historical-source limitations remain visible, and opening a page must not trigger generation. Existing preparation/research disclosures are historical preparation records when a completed supplemental review is present.

## Briefing impact colors (D-BRF-01/02)

Use `ImpactCue` from `@/components/common/ImpactCue` for business-impact labels and evidence headings. Positive uses a green upward symbol, negative a red warning, mixed an amber balance, and watch/undetermined a neutral question mark. Always retain the textual label; icons are decorative and hidden from assistive technology. `badge` adds a tinted pill, and `icon="check"` / `icon="calendar"` marks confirmed facts / next events. Use `zoop-positive` / `zoop-mixed` tokens with their dark-theme overrides; existing `zoop-alert` / muted tokens cover other states. Body text and quotations keep their normal contrast. These business-impact colors never change the existing red/blue quote rise/fall convention or stored assessment values.

## Reviewed issue grouping and selection rationale (D-BRF-01/02)

`issueReading` is an optional, source-bound reading review, separate from verified model output. Only explicitly reviewed dependent event components may share a compact card; same company or document alone never triggers grouping. Bind round/result/cutoff and exact citations; invalid metadata restores original cards with a reliability warning. Full reading and the grouped card's archive preserve original events, evidence, assessments and feedback targets. Partial personal views cannot acquire hidden members through grouping.

Show selection importance and what is new beneath each title. Place recorded direct event parties before related companies and show each connection's verified reason. Display common facts once in neutral colors. Compact positive/risk sections show a complete existing sentence with the remaining text expandable; do not invent a balanced pair. Use `다음 확인사항` for undated/longer-term conditions. Retain price baselines and causality limits. Both reading modes use a 1040px maximum desktop content width; retain the mobile layout padding and single issue column. Keep original response selection/versions in the preserved-publication subtree. Previous-round loading and error states must not be rendered as missing history. See `docs/development/briefing-issue-reading.md`.
