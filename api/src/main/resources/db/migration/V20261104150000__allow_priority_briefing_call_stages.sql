-- Additive producer revision; keep every historical receipt and original stage value.
ALTER TABLE briefing_selected_generation_calls DROP CONSTRAINT briefing_selected_generation_calls_stage_check;
ALTER TABLE briefing_selected_generation_calls ADD CONSTRAINT briefing_selected_generation_calls_stage_check
 CHECK(stage IN ('analysis','analysis-verification','priority-personal','priority-personal-check'));
