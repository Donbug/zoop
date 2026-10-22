package com.zoop.briefing.replay;

import static org.assertj.core.api.Assertions.*;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.node.ObjectNode;

@Tag("briefing-replay-postgres") // Cross-language fixture belongs to the opt-in gate, not Python-free unit tests.
class BriefingCompanySchemasTest {
    @TempDir Path root;
    StrictJson.Obj frozen;
    @BeforeEach void exportActualPythonFormats() throws Exception {
        var process = new ProcessBuilder("python3", Path.of("scripts/briefing_company_schema_fixture.py").toAbsolutePath().toString(), root.toString())
                .redirectErrorStream(true).redirectOutput(root.resolve("fixture.log").toFile()).start();
        assertThat(process.waitFor()).withFailMessage(() -> { try { return Files.readString(root.resolve("fixture.log")); } catch(Exception e) { return e.toString(); } }).isZero();
        frozen = StrictJson.parseObject(Files.readAllBytes(root.resolve("frozen.json")));
    }
    @Test void serverContractEqualsAllActualPythonOutlookAndShortReadingFormats() throws Exception {
        for (String prefix : List.of("company_outlook_", "company_reading_")) for (String phase : List.of("generation", "verification")) {
            var format = StrictJson.parseObject(Files.readAllBytes(root.resolve(prefix + phase + ".json")));
            assertThat(BriefingCompanySchemas.format(prefix, phase, frozen)).isEqualTo(format.node());
            assertThatCode(() -> recorded(prefix, phase, (ObjectNode) format.node())).doesNotThrowAnyException();
        }
    }
    @Test void trueOnlyVerifierAndAlteredStrictnessAreRejectedEvenWithValidByteHashesAndUsage() throws Exception {
        for (String prefix : List.of("company_outlook_", "company_reading_")) {
            ObjectNode format = BriefingCompanySchemas.format(prefix, "verification", frozen);
            ((ObjectNode) format.at("/schema/properties/checks/items/properties/supported")).putArray("enum").add(true);
            assertThatThrownBy(() -> recorded(prefix, "verification", format)).isInstanceOf(IllegalArgumentException.class).hasMessageContaining("response_schema");
            ObjectNode loose = BriefingCompanySchemas.format(prefix, "verification", frozen).put("strict", false);
            assertThatThrownBy(() -> recorded(prefix, "verification", loose)).isInstanceOf(IllegalArgumentException.class).hasMessageContaining("response_schema");
        }
    }
    private void recorded(String prefix, String phase, ObjectNode format) throws Exception {
        String version = prefix.equals("company_outlook_") ? "company-outlook-v1" : "company-reading-v1";
        String instructions;
        try (var stream = getClass().getResourceAsStream("/briefing/prompts/" + version + "/" + phase + ".md")) {
            instructions = new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        }
        ObjectNode data = StrictJson.newObject(); data.set("frozen", frozen.node());
        ObjectNode request = StrictJson.newObject().put("model", "gpt-6-luna").put("store", false).put("instructions", instructions)
                .put("input", new String(StrictJson.write(data), StandardCharsets.UTF_8));
        request.putObject("text").set("format", format);
        byte[] bytes = StrictJson.write(request); String digest = Canonical.sha256(bytes);
        ObjectNode response = StrictJson.newObject().put("id", "authored-response").put("status", "completed");
        response.putObject("usage").put("input_tokens", 1).put("output_tokens", 2);
        response.putArray("output").addObject().put("type", "message").putArray("content").addObject().put("type", "output_text").put("text", "{}");
        byte[] answer = StrictJson.write(response); Path calls = root.resolve("calls"); Files.createDirectories(calls);
        Files.write(calls.resolve(digest + ".request.json"), bytes); Files.write(calls.resolve(digest + ".response.json"), answer);
        ObjectNode receipt = StrictJson.newObject().put("responseSha256", Canonical.sha256(answer)).put("stage", prefix + phase)
                .put("model", "gpt-6-luna").put("usageKnown", true).put("httpStatus", 200).put("status", "completed")
                .put("responseId", "authored-response").put("inputTokens", 1).put("outputTokens", 2);
        BriefingCompanyOutlookRules.recordedCall(digest, phase, frozen, Map.of(digest, receipt), root, new HashSet<>(), prefix, version);
    }
}
