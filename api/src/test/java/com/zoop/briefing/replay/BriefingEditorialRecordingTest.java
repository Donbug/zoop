package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.junit.jupiter.api.Assertions.*;

class BriefingEditorialRecordingTest {
    @TempDir Path output;
    @Test void editorialReceiptUsesItsOwnFrozenContractWithoutNewsEditionContext() throws Exception {
        output = output.toRealPath();
        var request = StrictJson.newObject().put("model", "gpt-6-luna").put("store", false).put("input", "{\"issues\":[]}");
        request.putObject("text").putObject("format").put("name", "editorial_freshness");
        var response = StrictJson.newObject().put("status", "completed").put("id", "authored");
        response.putObject("usage").put("input_tokens", 10).put("output_tokens", 5);
        response.putArray("output").addObject().put("type", "message").putArray("content").addObject()
                .put("type", "output_text").put("text", "{}");
        byte[] raw = StrictJson.write(request), answer = StrictJson.write(response); String digest = Canonical.sha256(raw);
        Path calls = Files.createDirectory(output.resolve("calls"));
        Files.write(calls.resolve(digest+".request.json"), raw); Files.write(calls.resolve(digest+".response.json"), answer);
        var receipt = StrictJson.newObject().put("requestDigest", digest).put("responseSha256", Canonical.sha256(answer))
                .put("model", "gpt-6-luna").put("stage", "editorial_freshness").put("responseId", "authored")
                .put("status", "completed").put("usageKnown", true).put("httpStatus", 200).put("inputTokens", 10).put("outputTokens", 5);
        var result = BriefingGroupedSimulationRules.recording(StrictJson.Obj.of(receipt), output, true);
        assertTrue(result.input().array("issues").isEmpty());
        assertTrue(result.answer().node().isEmpty());
        receipt.put("responseSha256", "a".repeat(64));
        assertThrows(IllegalArgumentException.class, () -> BriefingGroupedSimulationRules.recording(StrictJson.Obj.of(receipt), output, true));
    }
    @Test void allowedIssueManifestCannotOmitAProviderSchemaCandidate() {
        var provider = StrictJson.parseObject("{\"text\":{\"format\":{\"schema\":{\"properties\":{\"selected\":{\"items\":{\"anyOf\":[{\"properties\":{\"issueId\":{\"enum\":[\"issue-authored\"]}}}]}}}}}}}");
        var valid = StrictJson.parseObject("{\"selectionEligibility\":{\"allowedIssueIds\":[\"issue-authored\"]}}");
        assertDoesNotThrow(() -> BriefingGroupedSimulationRules.eligibilityManifest(valid, provider, java.util.Set.of("issue-authored")));
        var omitted = StrictJson.parseObject("{\"selectionEligibility\":{\"allowedIssueIds\":[]}}");
        assertThrows(IllegalArgumentException.class, () -> BriefingGroupedSimulationRules.eligibilityManifest(omitted, provider, java.util.Set.of("issue-authored")));
    }

}
