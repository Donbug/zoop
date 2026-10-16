# Mock portfolio fixture

`src/main/resources/portfolio/mock-portfolios.json` is a fixed, synthetic project fixture. It does not come from a brokerage, a user account, or a live market feed. Account IDs, cash amounts, quantities, average purchase prices, and the `2026-10-16T00:00:00Z` reference time are demonstration values.

The fixture contains two profiles with holdings and one valid profile with no holdings. It also distinguishes a real zero cash balance from cash that is not provided. Company IDs and display names refer to the project's company catalog; the quantities and prices remain synthetic and are not synchronized with that catalog.

The API never accepts brokerage passwords, certificates, or other brokerage credentials. It does not execute trades or edit/refresh the fixture. Market quotes and valuation are not supplied by this fixture; portfolio responses report quote and valuation availability separately from the immutable holding values.

The profile order is stable and is used by the opaque list cursor. Changes to profile identifiers or ordering invalidate outstanding cursors; clients should restart listing from the first page after receiving `INVALID_CURSOR`.

Traceability: FS009, FS010, FS062; screens D-ONB-02 and D-MY-01; WBS 6.3.2 and 6.4.4.
