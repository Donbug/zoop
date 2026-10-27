package com.zoop.briefing.replay;

import static org.assertj.core.api.Assertions.*;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** Authored provider recordings exercise the real import boundary, not a true-only verifier. */
class BriefingCompanyCardRulesTest {
    @TempDir Path root;
    @Test void acceptsCardRolesWithoutChangingReadingPriceOrFullAnalysis() throws Exception {
        var f = fixture(true, "PASS");
        var before = f.projection.at("/companies/0/reading").deepCopy();
        var price = f.projection.at("/companies/0/price").deepCopy();
        apply(f);
        assertThat(f.projection.at("/companies/0/reading")).isEqualTo(before);
        assertThat(f.projection.at("/companies/0/price")).isEqualTo(price);
        assertThat(f.projection.at("/companies/0/card/title/text").stringValue()).isEqualTo("합성 title");
        assertThat(f.projection.at("/companies/0/outlook").stringValue()).isEqualTo("원래 전문 보존");
    }
    @Test void factualSupportAloneCannotOverrideAFailedQualityCheck() throws Exception {
        var f = fixture(false, "PASS");
        assertThatThrownBy(() -> apply(f)).isInstanceOf(IllegalArgumentException.class).hasMessageContaining("quality_check");
    }
    @Test void cardCannotReplacePricesEvenWhenWithheldOrGivenANewVersion() throws Exception {
        for(String status:List.of("PASS","WITHHELD"))for(boolean attach:List.of(true,false)) {
            var f=fixture(true,status);ObjectNode row=(ObjectNode)f.row.node().deepCopy();
            var before=f.projection.deepCopy();
            if(attach)row.putObject("prices").putObject("A").put("value","999.00");
            else row.put("pricePolicy","connected");
            row.remove("resultVersion");row.put("resultVersion","card-v1-"+Canonical.digest(row));
            assertThatThrownBy(()->apply(new Fixture(StrictJson.Obj.of(row),f.original,f.projection,f.receipts)))
                .hasMessageContaining("card_prices_forbidden");
            assertThat(f.projection).isEqualTo(before);
        }
    }
    @Test void withheldQualityNeverProjectsDraftSentences() throws Exception {
        var f = fixture(false, "WITHHELD");
        apply(f);
        assertThat(f.projection.at("/companies/0/card/status").stringValue()).isEqualTo("WITHHELD");
        assertThat(f.projection.at("/companies/0/reading").has("title")).isFalse();
        assertThat(f.projection.at("/companies/0/reading").has("description")).isFalse();
    }
    @Test void rejectsForeignCompanyEvidenceAndTamperedProviderResponse() throws Exception {
        var f = fixture(true, "PASS");
        ObjectNode row = (ObjectNode) f.row.node().deepCopy();
        ((ObjectNode) row.at("/draft/companies/0/title")).putArray("evidenceIds").add("foreign");
        row.remove("resultVersion"); row.put("resultVersion", "card-v1-" + Canonical.digest(row));
        assertThatThrownBy(() -> apply(new Fixture(StrictJson.Obj.of(row), f.original, f.projection, f.receipts))).isInstanceOf(IllegalArgumentException.class);
        var path = root.resolve("calls/" + f.row.string("generationRequestDigest") + ".response.json");
        Files.writeString(path, "{}");
        assertThatThrownBy(() -> apply(f)).isInstanceOf(IllegalArgumentException.class).hasMessageContaining("recording");
    }
    @Test void refusesAnotherCutoffEvenWithAFreshDigest() throws Exception {
        var f = fixture(true, "PASS");
        ObjectNode row = (ObjectNode) f.row.node().deepCopy();
        ((ObjectNode) row.get("frozen")).put("cutoff", "2026-10-24T00:20:00Z");
        row.remove("resultVersion"); row.put("resultVersion", "card-v1-" + Canonical.digest(row));
        assertThatThrownBy(() -> apply(new Fixture(StrictJson.Obj.of(row), f.original, f.projection, f.receipts))).isInstanceOf(IllegalArgumentException.class).hasMessageContaining("full_analysis_binding");
    }
    record Fixture(StrictJson.Obj row, StrictJson.Obj original, ObjectNode projection, Map<String, JsonNode> receipts) { }
    private void apply(Fixture f) {
        BriefingCompanyReadingRules.apply(f.row, f.original, f.projection, f.receipts, new HashSet<>(), root);
    }
    private Fixture fixture(boolean specific, String status) throws Exception {
        var original = StrictJson.parseObject("{\"roundId\":\"r\",\"edition\":\"morning\",\"cutoff\":\"2026-10-23T00:20:00Z\",\"status\":\"PASS\",\"resultVersion\":\"full-exact-version\",\"draft\":{\"companies\":[{\"companyId\":\"A\",\"assessment\":\"watch\"}]},\"frozen\":{\"targets\":[{\"companyId\":\"A\",\"sourceIds\":[\"e\"]}],\"sources\":{\"e\":{\"quote\":\"authored observation\"}}}}");
        ObjectNode frozen = StrictJson.newObject().put("schemaVersion", BriefingCompanyReadingRules.SCHEMA_CARD)
                .put("roundId", "r").put("edition", "morning").put("cutoff", original.string("cutoff"))
                .put("companyResultVersion", original.string("resultVersion"));
        frozen.set("draft", original.raw("draft")); frozen.set("targets", original.object("frozen").raw("targets"));
        frozen.set("sources", original.object("frozen").raw("sources"));
        ObjectNode draft = StrictJson.newObject(); ObjectNode company = draft.putArray("companies").addObject().put("companyId", "A");
        for (String key : List.of("topic", "title", "description")) {
            var statement = company.putObject(key).put("text", key.equals("fact") ? "합성 title" : "합성 " + key);
            statement.putArray("evidenceIds").add("e");
        }
        ObjectNode verification = StrictJson.newObject(); var check = verification.putArray("checks").addObject()
                .put("companyId", "A").put("supported", true).put("reason", "원문 지지와 품질 판정을 분리한 합성 시험");
        var quality = check.putObject("quality");
        for (String key : List.of("concise", "distinctRoles", "qualifiersPreserved", "noUnsupportedClaim")) quality.put(key, !key.equals("qualifiersPreserved") || specific);
        Map<String, JsonNode> receipts = new HashMap<>();
        String generation = record("generation", frozen, draft, draft, receipts);
        String validation = record("verification", frozen, draft, verification, receipts);
        ObjectNode row = StrictJson.newObject().put("roundId", "r").put("cutoff", original.string("cutoff"))
                .put("status", status).put("pricePolicy", "not_connected").put("generatedAt", "2026-10-23T01:00:00Z");
        row.set("frozen", frozen);
        var attempt = row.putArray("attempts").addObject().put("generationRequestDigest", generation).put("verificationRequestDigest", validation);
        attempt.set("draft", draft); attempt.set("verification", verification);
        if (status.equals("PASS")) {
            row.set("draft", draft); row.put("generationRequestDigest", generation).put("verificationRequestDigest", validation);
        } else row.putNull("draft");
        row.put("resultVersion", "card-v1-" + Canonical.digest(row));
        ObjectNode projection = StrictJson.newObject(); projection.putArray("companies").addObject().put("companyId", "A").put("outlook", "원래 전문 보존");
        ((ObjectNode) projection.at("/companies/0")).putObject("reading").put("status", "PASS").put("resultVersion", "original-reading");
        ((ObjectNode) projection.at("/companies/0")).putObject("price").put("value", "10.00");
        return new Fixture(StrictJson.Obj.of(row), original, projection, receipts);
    }
    private String record(String phase, ObjectNode frozen, ObjectNode draft, ObjectNode value, Map<String, JsonNode> receipts) throws Exception {
        String instructions;
        try (var stream = getClass().getResourceAsStream("/briefing/prompts/company-card-v1/" + phase + ".md")) {
            instructions = new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        }
        ObjectNode input = StrictJson.newObject(); input.set("frozen", frozen); input.set("draft", draft);
        ObjectNode request = StrictJson.newObject().put("model", "gpt-6-luna").put("store", false).put("instructions", instructions)
                .put("input", new String(StrictJson.write(input), StandardCharsets.UTF_8));
        request.putObject("text").set("format", BriefingCompanySchemas.format("company_card_", phase, StrictJson.Obj.of(frozen)));
        byte[] raw = StrictJson.write(request); String digest = Canonical.sha256(raw);
        ObjectNode response = StrictJson.newObject().put("id", "authored-" + phase).put("status", "completed");
        response.putObject("usage").put("input_tokens", 1).put("output_tokens", 2);
        response.putArray("output").addObject().put("type", "message").putArray("content").addObject().put("type", "output_text")
                .put("text", new String(StrictJson.write(value), StandardCharsets.UTF_8));
        byte[] answer = StrictJson.write(response); Files.createDirectories(root.resolve("calls"));
        Files.write(root.resolve("calls/" + digest + ".request.json"), raw); Files.write(root.resolve("calls/" + digest + ".response.json"), answer);
        receipts.put(digest, StrictJson.newObject().put("responseSha256", Canonical.sha256(answer)).put("stage", "company_card_" + phase)
                .put("model", "gpt-6-luna").put("usageKnown", true).put("httpStatus", 200).put("status", "completed")
                .put("responseId", "authored-" + phase).put("inputTokens", 1).put("outputTokens", 2).put("finishedAt", "2026-10-23T00:59:00Z"));
        return digest;
    }
}
