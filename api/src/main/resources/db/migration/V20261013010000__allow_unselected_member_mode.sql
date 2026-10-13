-- A new member has not chosen an onboarding mode yet. PostgreSQL CHECK
-- (mode IN ('assets', 'watchlist')) still rejects other non-NULL values.
ALTER TABLE members ALTER COLUMN mode DROP NOT NULL;
