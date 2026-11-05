# D-GRP-01 / D-GRP-07b · PR #570 second review

Captured on 2026-11-05 using the real application router and MapPage on
127.0.0.1:15744, `VITE_GRAPH_DATA_SOURCE=mock`, and a synthetic guest session.
Graph, quote and company fixtures are synthetic, not production observations or
a member portfolio. No environment, certificate or test-account files were read.

## Source and scope

Base is main `10d6e9d4`. Only the four #570 commits (`6318d481`, `e3ed050f`,
`896025ac`, `b7640896`) were replayed onto it before these second-review fixes.
The previous combined branch is preserved as
`backup/pr570-with-576-fix2-20261105`. PR #576 had already merged into main
at `10d6e9d4` before this work started; its layout is inherited from main.
Neither graph-arrange.ts nor graph-arrange.test.ts differs from main.
The existing FOCUS_FIT_ZOOM/spreadFrom/sameFocus code is also inherited from main;
removing it here would undo the separately merged work.

- Selection effects depend only on the selected node. Edge-only navigation reads
  the latest edge through an Effect Event without resetting centering or a fit.
- Selection camera capture happens only in that effect. New clicks wait for the
  route to commit before moving the camera; clicking the selected node can still
  recenter it. Path/tutorial/focus/flow selections cannot seed a return.
- Whole-graph fit follows panel and viewport resizes until direct camera input.
- A saved return includes the browser viewport dimensions. A different viewport
  discards the return, while an ordinary rail resize still restores it once.
- Mobile minimap is 144x96, desktop 192x128. The option and fallback reservation
  share a size function. Measured minimap bounds replace the fallback reservation.
  Breakpoint changes recreate the G6 plugin: its size update alone resizes the
  canvas but leaves the wrapper at the old size.
- The mobile tools popup sits above its zoom column, away from the minimap.

## Captures

| Image                                | Viewport | Check                                         |
| ------------------------------------ | -------- | --------------------------------------------- |
| desktop-1280-before.jpg              | 1280x900 | Camera immediately before NAVER selection.    |
| desktop-1280-selected.jpg            | 1280x900 | Actual company rail opens.                    |
| desktop-1280-returned.jpg            | 1280x900 | Closing restores the original camera.         |
| desktop-1280-fit-selected.jpg        | 1280x900 | Whole fit while the rail is open.             |
| desktop-1280-fit-closed.jpg          | 1280x900 | Closing refits the enlarged canvas.           |
| desktop-1920-selected.jpg            | 1920x900 | Company selected before browser resize.       |
| desktop-1280-resized-selected.jpg    | 1280x900 | Selected company after browser resize.        |
| desktop-1280-resized-closed.jpg      | 1280x900 | Closing preserves the resized camera.         |
| desktop-1920-focus-sidebar-light.jpg | 1920x900 | Focus bar and minimap with both rails, light. |
| desktop-1920-focus-sidebar-dark.jpg  | 1920x900 | Same arrangement, dark.                       |
| mobile-375-tools-light.jpg           | 375x812  | Tools popup and smaller minimap, light.       |
| mobile-375-focus-dark.jpg            | 375x812  | Focus bar and smaller minimap, dark.          |
| mobile-375-focus-tools-dark.jpg      | 375x812  | Focus popup does not cover the minimap.       |
| mobile-375-detail-dark.jpg           | 375x812  | Existing modal may cover the minimap.         |

## Measurements and limits

- At 1280, NAVER selection/close restored the exact minimap mask inline rectangle
  and the 16% displayed zoom. See measurements.json for original DOM values.
- Fit with the selected rail showed 10%; after closing it, the enlarged map was
  fitted again at 13%.
- After 1920 to 1280, closing retained 16% and the mask's top/left. Only mask width
  expanded with the canvas; it did not restore the old browser's camera.
- At 375, minimap: x=12.8, y=639.2, width=144, height=96. Zoom column:
  x=314.4, y=587.2, width=44, height=200 (157.6px horizontal separation).
  Focus bar: x=12.8, y=188.8, width=295.15, height=53.6.
  Focus tools popup: x=78.4, y=380.55, width=224, height=198.65. Its bottom is
  579.2, leaving 60px before the minimap. No overlap among these controls.
- The existing mobile modal can cover and block the background minimap, per the
  user's earlier decision. Modal height/snaps and tutorial flow were not changed.
- A guest has no holdings/watchlist rows. Sidebar-centering plus edge-only changes
  and queued fits are covered by the renderer regression test, rather than being
  claimed as a member-account browser walkthrough.
- The development console contained an expected HMR reload error from temporary
  source replacement for RED tests (01:23 UTC). Subsequent screenshot checks used
  reloaded code. A separate final fresh-tab console sweep could not be completed
  after the browser connection became unavailable on resume.

## Validation

Commands use COREPACK_ENABLE_DOWNLOAD_PROMPT=0 CI=true HUSKY=0
VITE_GRAPH_DATA_SOURCE=mock and corepack pnpm@10.34.6 from web/.

- Regression RED: 12 assertions/cases failed with the relevant source restored to
  the pre-fix HEAD (including the mobile popup placement check).
- Selection GREEN before the final popup placement: 92 tests passed.
- exec tsc -b: PASS.
- lint: PASS, no warnings.
- exec prettier --check .: PASS, including this evidence directory.
- build: PASS; existing large-chunk advisory only.
- exec vitest run --maxWorkers=1: 139 files / 1601 tests PASS;
  adminJobs.test.tsx alone had 4 failures (140 files / 1605 tests total),
  including two 5-second timeouts. Duration: 1517.78s.
- Isolated rerun: exec vitest run tests/admin/adminJobs.test.tsx --maxWorkers=1:
  all 18 tests PASS (20.18s), without code changes. The full-run failures did not
  reproduce in isolation. Admin source/tests have no diff from main.
