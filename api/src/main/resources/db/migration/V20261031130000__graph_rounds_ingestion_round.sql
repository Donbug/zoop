-- #55 (WBS 6.5.4) graph round automation, step A-6 (the round scheduler): the AI ingestion round the slot's run made.
--
-- The app's slot id (round_id, round-yyyyMMddTHHmm) and the AI side's ingestion round id (the tick's slot-<sha256>, #387 ①)
-- are two different ids. The run's status answers the latter and the freeze request (round-handoffs, #387 ②) names it, so it
-- lives on the row like the plan id. A slot without a run (no new material, the freeze-only slot after the operating hours)
-- keeps it NULL and asks for a carry-only freeze. Written with the stage change that learns it (plan_ready / analysis_done);
-- it is progress, not identity, so the row guard leaves it alone.
ALTER TABLE graph_rounds ADD COLUMN ingestion_round_id text;
