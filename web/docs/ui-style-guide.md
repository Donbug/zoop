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

## Graph feature port

D-GRP-01/01b uses `graph-view` for member/mode-scoped state and legend keys. G6 supplies the conditional desktop minimap. Saved zoom/pan is reused only when the map size is unchanged; otherwise the default layout opens. `MapDetailSheet` owns M-GRP-01 modal snaps and focus return; `IsolatedIssuesPanel` reuses the detail panel tokens.
