# Repository guidance

## UI and frontend work

Before changing a user-facing screen, route, component, responsive layout, or interaction:

1. Read `docs/wireframe/README.md`.
2. Find the relevant screen ID in `docs/wireframe/manifest.json`.
3. Inspect the linked board and individual screen image before implementation.
4. Keep the screen ID in implementation notes, tests, or handoff documentation so the change remains traceable.

Treat the wireframe as the visual and navigation reference. A static screenshot does not prove loading, error, empty, permission, or persistence behavior; verify those states against the requirements and screen-plan documents instead of inventing them.
