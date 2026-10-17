# Mock portfolio fixture

`src/main/resources/portfolio/mock-portfolios.json` is a fixed, synthetic project fixture. It does not come from a brokerage, a user account, or a live market feed. Account IDs, cash amounts, quantities, average purchase prices, and the `2026-10-16T00:00:00Z` reference time are demonstration values.

The fixture contains two profiles, and both have holdings. One profile has a real zero cash balance. Company IDs and display names refer to the project's company catalog; the quantities and prices remain synthetic and are not synchronized with that catalog.

The API never accepts brokerage passwords, certificates, or other brokerage credentials. It does not execute trades or edit/refresh the fixture. Market quotes are not supplied by this fixture. `GET /api/v1/portfolio` reads them from the configured quote provider and keeps the provider observation time separate from the fixture's `asOf` time. It calculates stock market values and weights only when every holding has a price in one currency. A missing price, mixed currencies, and a zero total remain distinct unavailable states; the API never substitutes a missing price with zero.

The profile order is stable and is used by the opaque list cursor. Changes to profile identifiers or ordering invalidate outstanding cursors; clients should restart listing from the first page after receiving `INVALID_CURSOR`.

Traceability: FS009, FS010, FS062; screens D-ONB-02 and D-MY-01; WBS 6.3.2 and 6.4.4.
