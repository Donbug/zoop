# D-GRP-01 / D-GRP-07b · PR #570 review verification

Captured on 2026-11-05 from the real application router and MapPage, using
`VITE_GRAPH_DATA_SOURCE=mock` and a synthetic guest session on localhost.
Quotes, companies and events are synthetic development fixtures, not public
market observations or a real member's portfolio. No environment, certificate,
credential or test-account files were read for these captures.

Base: PR #570 `896025ac` plus approved PR #576 head
`2847619afe379271075efb3bc763dd8919d1be8f`, followed by the camera review fixes.
The approved #576 layout implementation is preserved.

| Screenshot                                 | Viewport   | Check                                                                                    |
| ------------------------------------------ | ---------- | ---------------------------------------------------------------------------------------- |
| mobile-375-light.jpg                       | 375 × 812  | Always-visible minimap sits left of the zoom buttons.                                    |
| mobile-375-focus-dark.jpg                  | 375 × 812  | Direct focus entry; focus controls, minimap and zoom buttons do not overlap.             |
| desktop-1280-before.jpg                    | 1280 × 900 | Camera before selecting NAVER.                                                           |
| desktop-1280-selected.jpg                  | 1280 × 900 | Selection opens the actual company detail rail.                                          |
| desktop-1280-returned.jpg                  | 1280 × 900 | Closing the rail restores the preselection camera.                                       |
| desktop-1280-manual-retained.jpg           | 1280 × 900 | Minimap movement after return survives sidebar open/close.                               |
| desktop-1280-selection-manual-retained.jpg | 1280 × 900 | Minimap movement during selection survives closing the rail.                             |
| desktop-1920-focus-sidebar-light.jpg       | 1920 × 900 | Focus controls and minimap stay within the canvas beside the holdings/watchlist sidebar. |
| desktop-1920-focus-sidebar-dark.jpg        | 1920 × 900 | Same placement in dark mode.                                                             |

## Browser observations

- At 375 px the minimap rectangle was x=12.8..204.8, y=607.2..735.2;
  the zoom controls were x=314.4..358.4, y=587.2..787.2. Their horizontal
  separation was 109.6 px, with no overlap.
- At 1920 px with both rails open, the canvas started at x=304, focus controls
  at x=340.8, and the minimap ended at the canvas right edge x=1563.2.
- The 1280 px return preserved the displayed zoom (80%) and exactly restored
  the minimap viewport's inline position and dimensions.
- Direct minimap movement was kept after closing a selection and after toggling
  the sidebar. G6 rounds the viewport box during dragging; subsequent redraws
  return to fractional coordinates, so the DOM box can differ by under 1 px.
- A fresh final-code tab reported no console errors. Editing the effect's
  dependency list during development emitted one HMR warning before reload.
- The existing mobile detail modal may cover the minimap, as previously
  authorized; its layout and interaction were not changed.

## Review scope and remaining observation

The one-shot camera return relies on the existing ResizeObserver preserving
the projected canvas origin through closing-rail resize frames. User fits
queued together with deselection take precedence; a completed manual fit is
not repeated merely because its selection rail closes.

Separately, shrinking an already-selected desktop focus view directly to a
mobile viewport can retain its earlier zoom and crop nodes. A fresh mobile
focus entry fits correctly. This existing continuous-resize behavior was not
changed by altering #576's layout implementation in this review.
