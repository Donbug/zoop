import math
import unittest

from zoop_eval.stats import distribution, nearest_rank, union_length
from zoop_eval.timing import parse_trace, summarize

from support import Case, oracle, record, score


def span(span_id, kind, start, end, **extra):
    return {"spanId": span_id, "kind": kind, "name": span_id, "startMs": start, "endMs": end, **extra}


class TraceDerivation(Case):
    def test_parallel_spans_use_the_union_never_the_sum_as_wall_time(self):
        t = parse_trace({"startMs": 0, "endMs": 100, "spans": [
            span("a", "tool", 0, 60, costUsd=0), span("b", "tool", 40, 100, costUsd=0)]}, "t")
        self.assertEqual(t["wallMs"], 100)
        self.assertEqual(t["toolMs"], 100)  # not 120
        self.assertEqual(t["otherMs"], 0)
        self.assertTrue(t["parallelSpans"])
        self.assertEqual(t["toolCalls"], 2)

    def test_llm_and_tool_time_are_separated_and_gaps_are_other_time(self):
        t = parse_trace({"startMs": 10, "endMs": 110, "spans": [
            span("l", "llm", 10, 50, tokens={"input": 100, "output": 20}, costUsd=0.01),
            span("t", "tool", 50, 70, costUsd=0)]}, "t")
        self.assertEqual((t["llmMs"], t["toolMs"], t["otherMs"], t["wallMs"]), (40, 20, 40, 100))
        self.assertEqual((t["llmCalls"], t["toolCalls"]), (1, 1))
        self.assertEqual(t["tokens"], {"input": 100, "output": 20})
        self.assertAlmostEqual(t["costUsd"], 0.01)
        self.assertFalse(t["parallelSpans"])

    def test_nested_tool_span_inside_an_llm_span_is_contained_not_double_counted(self):
        t = parse_trace({"startMs": 0, "endMs": 50, "spans": [
            span("l", "llm", 0, 50, tokens={"input": 1, "output": 1}, costUsd=0),
            span("t", "tool", 10, 20, parentSpanId="l", costUsd=0)]}, "t")
        self.assertEqual((t["llmMs"], t["toolMs"], t["otherMs"]), (50, 10, 0))

    def test_missing_tokens_and_cost_stay_null_not_zero(self):
        t = parse_trace({"startMs": 0, "endMs": 10, "spans": [span("l", "llm", 0, 10)]}, "t")
        self.assertIsNone(t["tokens"])
        self.assertIsNone(t["costUsd"])
        self.assertEqual(t["llmCalls"], 1)

    def test_no_llm_spans_proves_zero_tokens_but_no_spans_at_all_proves_nothing(self):
        t = parse_trace({"startMs": 0, "endMs": 10, "spans": [span("t", "tool", 0, 5, costUsd=0)]}, "t")
        self.assertEqual(t["tokens"], {"input": 0, "output": 0})
        bare = parse_trace({"startMs": 0, "endMs": 10}, "t")
        for key in ("llmMs", "toolMs", "otherMs", "llmCalls", "toolCalls", "tokens", "costUsd"):
            self.assertIsNone(bare[key], key)
        self.assertEqual(bare["wallMs"], 10)

    def test_inconsistent_intervals_are_rejected(self):
        bad = {
            "negative start": {"startMs": -1, "endMs": 5},
            "end before start": {"startMs": 5, "endMs": 1},
            "span before record": {"startMs": 10, "endMs": 20, "spans": [span("a", "tool", 5, 15)]},
            "span after record": {"startMs": 0, "endMs": 20, "spans": [span("a", "tool", 5, 25)]},
            "span end before start": {"startMs": 0, "endMs": 20, "spans": [span("a", "tool", 9, 5)]},
            "duplicate span": {"startMs": 0, "endMs": 20, "spans": [span("a", "tool", 0, 5), span("a", "tool", 5, 9)]},
            "unknown parent": {"startMs": 0, "endMs": 20, "spans": [span("a", "tool", 0, 5, parentSpanId="zz")]},
            "child outside parent": {"startMs": 0, "endMs": 20, "spans": [span("p", "llm", 0, 5), span("c", "tool", 3, 8, parentSpanId="p")]},
            "tokens on a tool": {"startMs": 0, "endMs": 20, "spans": [span("a", "tool", 0, 5, tokens={"input": 1, "output": 1})]},
            "nan": {"startMs": 0, "endMs": math.nan},
            "string time": {"startMs": 0, "endMs": "20"},
            "boolean time": {"startMs": 0, "endMs": True},
            "negative cost": {"startMs": 0, "endMs": 20, "spans": [span("a", "tool", 0, 5, costUsd=-1)]},
            "unknown key": {"startMs": 0, "endMs": 20, "wall": 20},
        }
        for name, trace in bad.items():
            with self.subTest(name):
                self.rejected(lambda trace=trace: parse_trace(trace, "t"), "trace_invalid")

    def test_malformed_trace_inside_a_run_rejects_the_whole_run(self):
        run = oracle()
        record(run, "graph", "GT-A1")["trace"]["endMs"] = -5
        self.rejected(run, "trace_invalid")

    def test_non_string_parent_span_id_is_a_trace_invalid_rejection_not_a_traceback(self):
        for parent in (["a"], {"a": 1}, 7, True):
            with self.subTest(parent=parent):
                trace = {"startMs": 0, "endMs": 20, "spans": [span("a", "tool", 0, 5), span("b", "tool", 1, 4, parentSpanId=parent)]}
                self.rejected(lambda trace=trace: parse_trace(trace, "t"), "trace_invalid")


class Aggregation(Case):
    def test_nearest_rank_percentiles_match_the_ledger_definition(self):
        values = [float(i) for i in range(1, 21)]  # n=20
        self.assertEqual(nearest_rank(values, 0.50), 10.0)  # x[ceil(0.50*20)]
        self.assertEqual(nearest_rank(values, 0.95), 19.0)  # x[ceil(0.95*20)] = x[19]
        d = distribution(values)
        self.assertEqual((d["n"], d["p50"], d["p95"], d["max"], d["caveats"]), (20, 10.0, 19.0, 20.0, []))
        d = distribution([5.0, 1.0, 9.0])
        self.assertEqual((d["p50"], d["p95"], d["max"]), (5.0, 9.0, 9.0))
        self.assertEqual(len(d["caveats"]), 2)  # small-sample caveats for p50 and p95

    def test_empty_samples_are_null_with_a_caveat(self):
        d = distribution([])
        self.assertEqual((d["n"], d["p50"], d["p95"], d["max"]), (0, None, None, None))
        self.assertEqual(d["caveats"], ["no_samples"])

    def test_p95_with_fewer_than_twenty_samples_is_flagged(self):
        d = distribution([float(i) for i in range(1, 20)])
        self.assertTrue(any("p95_insufficient_samples" in c for c in d["caveats"]))
        self.assertEqual(d["p95"], d["max"])

    def test_union_length(self):
        self.assertEqual(union_length([(0, 10), (5, 15), (20, 30)]), 25)
        self.assertEqual(union_length([(0, 10), (2, 3)]), 10)
        self.assertEqual(union_length([]), 0)

    def test_records_without_trace_are_excluded_and_counted_not_treated_as_zero(self):
        with_trace = parse_trace({"startMs": 0, "endMs": 40, "spans": [span("t", "tool", 0, 40, costUsd=0)]}, "t")
        s = summarize([with_trace, None, None], "recorded_live_trace")
        self.assertEqual(s["population"], {"okRecords": 3, "withTrace": 1, "withoutTrace": 2})
        self.assertEqual(s["latencyMs"]["wall"]["n"], 1)
        self.assertEqual(s["costUsd"], {"known": 1, "unknown": 2, "total": 0})
        none = summarize([None], "recorded_live_trace")
        self.assertIsNone(none["costUsd"]["total"])
        self.assertIsNone(none["tokens"]["input"]["total"])
        self.assertEqual(none["latencyMs"]["wall"]["caveats"], ["no_samples"])

    def test_latency_is_never_summed_across_records(self):
        s = score(oracle())["timing"]["qa"]["all"]
        self.assertNotIn("totalMs", s["latencyMs"]["wall"])
        self.assertEqual(s["latencyMs"]["wall"]["n"], 9)
        self.assertEqual(s["semantics"], "authored_control_values_not_a_measurement")

    def test_tool_llm_and_overall_time_are_reported_apart_with_sample_counts(self):
        s = score(oracle())["timing"]["graph"]
        self.assertEqual(s["latencyMs"]["tool"]["n"], 5)
        self.assertEqual(s["latencyMs"]["tool"]["p50"], 100.0)  # union of the two overlapping spans, not 120
        self.assertEqual(s["latencyMs"]["wall"]["max"], 170.0)
        self.assertEqual(s["calls"]["tool"]["total"], 10)
        self.assertEqual(s["calls"]["llm"]["total"], 0)
        self.assertEqual(s["parallelRecords"], 5)

    def test_per_hop_latency_is_available_for_multi_hop_comparison(self):
        by_hop = score(oracle())["timing"]["qa"]["byHop"]
        self.assertEqual(set(by_hop), {"1", "2", "3"})
        self.assertLess(by_hop["1"]["latencyMs"]["wall"]["p50"], by_hop["3"]["latencyMs"]["wall"]["p50"])

    def test_only_ok_records_enter_timing_samples(self):
        run = oracle()
        r = record(run, "qa", "QA-1")
        r.update(status="error", detail="timeout")
        del r["output"]
        t = score(run)["timing"]["qa"]["all"]
        self.assertEqual(t["population"]["okRecords"], 8)


if __name__ == "__main__":
    unittest.main()
