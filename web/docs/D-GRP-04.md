# D-GRP-04 · WBS 6.6.24

Reference: `docs/wireframe/screens/D-GRP-04--node-619-7557.png`, board 03, `docs/screen-plan/captures/D-GRP-04.json`, FS023/024/055, ERD v6 and OpenAPI `EdgeDetail`.

## Try it

1. Run `pnpm dev` from `web`, open the map.
2. Select a dashed company–company **사건 공유** edge, or open a company and choose a **관련 기업** row. Tab/Enter on the map's accessible connection buttons also works.
3. The panel shows relation type, direction, endpoints and common events. A red **후속 사건** edge opens the directed event relation variant.
4. **근거 N건 보기** opens D-GRP-05 with all relation evidence; each event's button opens just its own evidence. Closing the evidence window preserves the selected relation and URL.
5. Endpoint/event titles select that node. **AI에게 묻기** only hands the target/context to the existing AI store; AI generation is not implemented here.
6. Close/Escape clears selection only; mode/filter/focus and graph viewport remain. Browser Back restores selection.

Direct mock example: `/?mode=all&select=edge%3Amock-follows-1`.

## Mock boundaries

`getRelation` is mock-only, with no HTTP fallback even in a production build. The existing graph loader's environment policy is unchanged (use dev mode for the mock map). Synthetic evidence IDs always resolve locally, including relation evidence in production builds. There is no backend/API implementation in this change.

`VITE_RELATION_MOCK_SCENARIO`: `success` (default), `empty`, `no-evidence`, `error`, `forbidden`. Set in `.env.local` and restart Vite to exercise states. `error` remains failing until the scenario is changed; tests also verify recovery on retry.

`SHARES_ISSUE` derives from approved common Issue IDs and collects unique evidence IDs from those issues; it is never persisted as a SQL relation. `FOLLOWS` uses its own relation evidence, separate from the evidence of its endpoint events. `INVOLVES`/`STRUCTURALLY_RELATED_TO` edges are not selectable as D-GRP-04 relations. The screen-plan explicitly allows FOLLOWS; the future getCompanyRelation API description is company-focused, so confirm that contract before API integration.

Unavailable round/version/asOf contexts fail explicitly; the mock never substitutes the latest snapshot. Verification dates come only from `basis.verifiedAt`, not `metadata.asOf` or article publication. Mock basis verification is intentionally null. Trade, supply, competition, business scope, current validity and causality are not inferred.

Visual primitives are shared with the company/event/evidence panels via `detail-panel-styles.ts`; see `ui-style-guide.md` before editing.
