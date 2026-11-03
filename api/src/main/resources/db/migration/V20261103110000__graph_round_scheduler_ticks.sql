-- The round schedulers that are alive (#55 PR-P4): each writer process beats its own row every interval from a small thread of its
-- own (so a long pass does not look like a dead writer), with the time of its last pass and a digest of its slot calendar. The
-- public web reads these rows to show the scheduler in the admin overview and to accept the admin round commands only while a
-- scheduler with the same calendar is alive. beat_at is the database's clock, and liveness is judged against it too, so the two
-- hosts' clocks do not matter. This is a status, not a record: a row is updated in place, removed when its process stops, and
-- rows silent for a day are pruned.
CREATE TABLE graph_round_scheduler_ticks (
    owner text PRIMARY KEY CHECK (owner ~ '^[A-Za-z0-9.-]{1,64}-[a-f0-9]{8}$'),
    started_at timestamptz NOT NULL,
    beat_at timestamptz NOT NULL,
    interval_ms bigint NOT NULL CHECK (interval_ms > 0),
    last_pass_at timestamptz,
    calendar_digest text NOT NULL CHECK (calendar_digest ~ '^[a-f0-9]{64}$')
);
