package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.node.ObjectNode;
import static org.assertj.core.api.Assertions.*;

class BriefingEditorialCorrectionHistoryTest {
    @TempDir Path temporary;

    private ObjectNode input() {
        return (ObjectNode) StrictJson.parseObject("""
            {"window":{"from":"2026-10-22T00:20:00Z","to":"2026-10-22T08:30:00Z"},"reports":[],
             "issues":[{"issueId":"i","priorReportIds":[],"newEvidence":[{"evidenceId":"e","quote":"고정 원문"}]}]}
            """).node();
    }
    private ObjectNode answer(String decision) {
        var out = StrictJson.newObject(); var row = out.putObject("i");
        row.put("decision", decision).put("reason", "합성 보정 기록"); row.putArray("deltaEvidenceIds");
        return out;
    }
    private StrictJson.Obj record(Path output, ObjectNode input, ObjectNode answer) throws Exception {
        var request = StrictJson.newObject().put("model", "gpt-6-luna").put("store", false)
                .put("input", new String(StrictJson.write(input), java.nio.charset.StandardCharsets.UTF_8));
        request.put("instructions", new String(getClass().getResourceAsStream("/briefing/prompts/editorial-freshness-v3/review.md").readAllBytes(), java.nio.charset.StandardCharsets.UTF_8));
        request.putObject("text").putObject("format").put("name", "editorial_freshness");
        var response = StrictJson.newObject().put("id", "authored-local-only").put("status", "completed");
        response.putObject("usage").put("input_tokens", 10).put("output_tokens", 5);
        response.putArray("output").addObject().put("type", "message").putArray("content").addObject()
                .put("type", "output_text").put("text", new String(StrictJson.write(answer), java.nio.charset.StandardCharsets.UTF_8));
        byte[] raw = StrictJson.write(request), reply = StrictJson.write(response); String digest = Canonical.sha256(raw);
        Files.createDirectories(output.resolve("calls"));
        Files.write(output.resolve("calls/"+digest+".request.json"), raw);
        Files.write(output.resolve("calls/"+digest+".response.json"), reply);
        return StrictJson.Obj.of(StrictJson.newObject().put("requestDigest", digest).put("responseSha256", Canonical.sha256(reply))
                .put("model", "gpt-6-luna").put("stage", "editorial_freshness").put("status", "completed")
                .put("responseId", "authored-local-only").put("httpStatus", 200).put("usageKnown", true).put("inputTokens", 10).put("outputTokens", 5));
    }
    private Fixture fixture(boolean validOrigin) throws Exception {
        Path output = Files.createTempDirectory(temporary, "history-").toRealPath();
        var oldInput = input(); var oldAnswer = answer(validOrigin ? "REPEAT" : "MATERIAL_UPDATE");
        var original = record(output, oldInput, oldAnswer);
        var correctedInput = oldInput.deepCopy();
        correctedInput.putObject("editorialCorrection").put("attempt", 1).put("failure", "editorial_delta_binding")
                .put("originalRequestDigest", original.string("requestDigest"))
                .put("originalResponseSha256", original.string("responseSha256"))
                .put("instruction", "같은 원문에서 delta 규칙만 재검증").set("previousReply", oldAnswer.deepCopy());
        var corrected = record(output, correctedInput, answer("REPEAT"));
        var current = input();
        var report = StrictJson.newObject().put("reportId", "new-history").put("availableBefore", "2026-10-21T00:00:00Z");
        current.withArray("reports").add(report);
        ((ObjectNode) current.withArray("issues").get(0)).withArray("priorReportIds").add("new-history");
        var layer = StrictJson.newObject().put("promptVersion", "editorial-freshness-v3");
        var row = layer.putArray("rounds").addObject().put("requestDigest", "active-request");
        row.set("window", current.get("window").deepCopy()); row.set("frozen", current);
        row.set("decisions", answer("DISTINCT_EVENT"));
        var receipts = new LinkedHashMap<String, StrictJson.Obj>();
        // The pair is deliberately ordered repair-first: audit must not depend on ledger order.
        receipts.put(corrected.string("requestDigest"), corrected); receipts.put(original.string("requestDigest"), original);
        return new Fixture(output, layer, Map.of("new-history", StrictJson.Obj.of(report)), receipts, original, corrected, correctedInput);
    }
    private void audit(Fixture f) {
        var owned = new HashSet<String>();
        BriefingEditorialRules.historicalAccounting(StrictJson.Obj.of(f.layer), f.reports, f.receipts, owned, f.output);
        assertThat(owned).containsExactlyInAnyOrderElementsOf(f.receipts.keySet());
    }
    private void replaceCorrection(Fixture f, ObjectNode input, ObjectNode answer) throws Exception {
        f.receipts.remove(f.corrected.string("requestDigest"));
        var replacement = record(f.output, input, answer);
        f.receipts.put(replacement.string("requestDigest"), replacement);
    }
    @Test void failedOriginalAndSuccessfulRepairStayAccountingOnlyAfterHistoryGrows() throws Exception {
        var f = fixture(false); var before = f.layer.deepCopy(); audit(f);
        assertThat(f.layer).isEqualTo(before);
        var archive = StrictJson.newObject(); archive.set("editorialReview", f.layer);
        var selected = BriefingEditorialRules.decision(StrictJson.Obj.of(archive), StrictJson.Obj.of(input().get("window")), "i");
        assertThat(selected.get("decision").stringValue()).isEqualTo("DISTINCT_EVENT");
        assertThat(selected.get("reviewRequestDigest").stringValue()).isEqualTo("active-request");
    }
    @Test void invalidUnpairedOriginalCannotBeLaunderedAsAccounting() throws Exception {
        var f = fixture(false); f.receipts.remove(f.corrected.string("requestDigest"));
        assertThatThrownBy(() -> audit(f)).hasMessageContaining("historical_decision");
    }
    @Test void correctionMustReferenceExactRecordedOriginalHashAndReply() throws Exception {
        for (String field : List.of("originalResponseSha256", "previousReply", "originalRequestDigest")) {
            var f = fixture(false); var input = f.correctedInput.deepCopy(); var correction = (ObjectNode) input.get("editorialCorrection");
            if (field.equals("previousReply")) correction.set(field, answer("REPEAT")); else correction.put(field, "a".repeat(64));
            replaceCorrection(f, input, answer("REPEAT"));
            assertThatThrownBy(() -> audit(f)).isInstanceOf(IllegalArgumentException.class);
        }
    }
    @Test void originalMustExistAndActuallyHaveOnlyTheKnownDeltaFailure() throws Exception {
        var f = fixture(false); f.receipts.remove(f.original.string("requestDigest"));
        assertThatThrownBy(() -> audit(f)).hasMessageContaining("historical_correction_origin");
        var valid = fixture(true);
        assertThatThrownBy(() -> audit(valid)).hasMessageContaining("historical_correction_failure");
    }
    @Test void repairCannotKeepBadDeltaOrChangeTheOriginalEvidence() throws Exception {
        var f = fixture(false); replaceCorrection(f, f.correctedInput, answer("MATERIAL_UPDATE"));
        assertThatThrownBy(() -> audit(f)).hasMessageContaining("historical_correction_answer");
        var changed = fixture(false); var modified = changed.correctedInput.deepCopy();
        ((ObjectNode) modified.at("/issues/0/newEvidence/0")).put("quote", "변조한 원문");
        replaceCorrection(changed, modified, answer("REPEAT"));
        assertThatThrownBy(() -> audit(changed)).hasMessageContaining("historical_current_evidence");
    }
    private record Fixture(Path output, ObjectNode layer, Map<String, StrictJson.Obj> reports,
            Map<String, StrictJson.Obj> receipts, StrictJson.Obj original, StrictJson.Obj corrected, ObjectNode correctedInput) { }
}
