# Frontend implementation guidance

Before any UI change, read `docs/ui-style-guide.md` (relative to this directory) and the repository wireframe guidance. Keep the screen ID in code/tests/handoff notes.

- Prefer Tailwind utilities and the existing shared tokens/components over new CSS files.
- For detail panels, import `panelStyles` from `@/components/common/detail-panel-styles`. Do not duplicate font sizes, borders, close buttons, action grids or spacing in screen-specific CSS.
- D-GRP-03 company panel is the visual baseline. Update shared tokens/styles and verify D-GRP-02/03/04/05 together if the baseline changes.
- New reusable patterns belong in `src/components/common`; document their import and usage in `docs/ui-style-guide.md`.
- Do not replace loading/error/empty/permission behavior with screenshots or invented data. Mock content must be visibly labeled and follow the ERD and API consumer contract.
- Run relevant tests, `pnpm lint` and `pnpm build` in `web`. Preserve unrelated changes.
