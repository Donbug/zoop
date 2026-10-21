package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

class BriefingPresentationRulesTest {
    @TempDir Path output;
    private static final String BODY = "머리😀정확한 인용입니다.뒤 문맥입니다.";
    private static final int START = 3, END = 13;

    private BriefingPresentationRules.Evidence evidence() {
        return new BriefingPresentationRules.Evidence("e1", "doc", "sha256-" + Canonical.sha256(BODY), Canonical.sha256(BODY), BODY,
                slice(BODY, START, END), START, END, "기사 제목", "publisher", "https://example.invalid/article", "2026-10-02T00:00:00Z", "news");
    }
    private ObjectNode context() {
        return StrictJson.newObject().put("text", slice(BODY, 1, 18)).put("start", 1).put("end", 18).put("quoteStart", START).put("quoteEnd", END).put("offsetUnit", "unicode_code_point");
    }
    private static String slice(String value, int from, int to) { return value.substring(value.offsetByCodePoints(0, from), value.offsetByCodePoints(0, to)); }
    private ObjectNode payload(String id, String... events) {
        ObjectNode payload = StrictJson.newObject().put("id", id).put("date", "2026-10-02").put("edition", "morning"); payload.putObject("metadata").put("requestId", "fixed-run").putArray("failures");
        ArrayNode items = payload.putArray("items"); int rank = 1;
        for (String event : events) {
            ObjectNode item = items.addObject().put("eventId", event).put("rank", rank++).put("title", "제목 " + event).put("reason", "근거 있는 선정")
                    .put("evidenceCount", 1).putNull("eventTime").put("timePrecision", "unknown").put("reportedAt", "2026-10-02T00:00:00Z");
            item.putArray("evidenceIds").add("e1"); item.putArray("companies").addObject().put("id", "company").put("name", "회사");
            item.putObject("summary").put("text", "검증 문장").put("generatedAt", "2026-10-20T00:00:00Z").put("resultVersion", "v1").putArray("evidenceIds").add("e1");
        }
        return payload;
    }
    private ObjectNode generation(String... events) {
        ObjectNode value = StrictJson.newObject(); ArrayNode items = value.putArray("items");
        for (String event : events) items.addObject().put("issueId", event).putArray("claims").addObject().put("text", "검증 문장").put("type", "fact").putArray("evidenceIds").add("e1");
        return value;
    }
    private ObjectNode input(String... events) {
        ObjectNode value = StrictJson.newObject();
        for (String event : events) value.putObject(event).putArray("evidence").addObject().put("id", "e1").set("bodyContext", context());
        return value;
    }
    private void details(ObjectNode supplied, ObjectNode snapshot) {
        BriefingPresentationRules.details(payload("round", "event"), snapshot, StrictJson.Obj.of(generation("event")), StrictJson.Obj.of(supplied), Map.of("e1", evidence()));
    }
    private ObjectNode wrapper() throws Exception {
        output = output.toRealPath();
        ObjectNode base = StrictJson.newObject().put("runId", "base"); base.putObject("briefingRecovery").put("runId", "recovery");
        byte[] bytes = (Canonical.write(base) + "\n").getBytes(java.nio.charset.StandardCharsets.UTF_8); Files.write(output.resolve("base-presentation-bundle.json"), bytes);
        ObjectNode full = base.deepCopy(); full.putObject("presentationEnrichment").put("schemaVersion", BriefingPresentationRules.SCHEMA)
                .put("runId", "presentation").put("userInboxRef", "inbox/authored.md").put("baseBundleSha256", Canonical.sha256(bytes)).putArray("rounds"); return full;
    }
    @Test void wrapperPreservesTheExactOriginalRecoveryBytesAndJson() throws Exception {
        ObjectNode full = wrapper(); byte[] bytes = Files.readAllBytes(output.resolve("base-presentation-bundle.json"));
        var loaded = BriefingPresentationRules.load(StrictJson.Obj.of(full), output, "inbox/authored.md");
        assertArrayEquals(bytes, loaded.baseBytes()); assertFalse(loaded.baseBundle().has("presentationEnrichment"));
        Files.writeString(output.resolve("base-presentation-bundle.json"), new String(bytes).strip());
        assertThrows(IllegalArgumentException.class, () -> BriefingPresentationRules.load(StrictJson.Obj.of(full), output, "inbox/authored.md"));
    }
    @Test void modifiedOriginalCannotBeReplacedByAnHonestSidecar() throws Exception {
        ObjectNode full = wrapper().put("runId", "changed");
        var failure = assertThrows(IllegalArgumentException.class, () -> BriefingPresentationRules.load(StrictJson.Obj.of(full), output, "inbox/authored.md"));
        assertTrue(failure.getMessage().contains("base_json_unchanged"));
    }
    @Test void authoredBundleCannotRaiseTheDefaultLimitButApprovedImportRemainsBounded() throws Exception {
        ObjectNode full = wrapper();
        ((ObjectNode) full.path("presentationEnrichment")).put("maximumPaidCallsIncludingPrior", 415);
        assertThrows(IllegalArgumentException.class, () -> BriefingPresentationRules.load(StrictJson.Obj.of(full), output, "inbox/authored.md"));
        assertNotNull(BriefingPresentationRules.load(StrictJson.Obj.of(full), output, "inbox/authored.md", 415));
        ((ObjectNode) full.path("presentationEnrichment")).put("maximumPaidCallsIncludingPrior", 416);
        assertThrows(IllegalArgumentException.class, () -> BriefingPresentationRules.load(StrictJson.Obj.of(full), output, "inbox/authored.md", 415));
    }
    @Test void expandedRuntimeBudgetRequiresASeparateApprovalReferenceAndHardCeiling() throws Exception {
        wrapper();
        Path source = output.resolve("source.jsonl"), bundle = output.resolve("bundle.json"), artifacts = Files.createDirectory(output.resolve("artifacts"));
        Files.writeString(source, "{}"); Files.writeString(bundle, "{}");
        String sha = Canonical.sha256(Files.readAllBytes(source));
        assertEquals(400, new BriefingReplaySettings(source, bundle, artifacts, output.resolve("grants.json"), output.resolve("manifest.json"), sha, "inbox/authored.md").maximumPaidCalls());
        for (String ref : new String[] {null, "", "approval.txt"}) assertThrows(IllegalArgumentException.class, () ->
                new BriefingReplaySettings(source, bundle, artifacts, output.resolve("grants.json"), output.resolve("manifest.json"), sha, "inbox/authored.md", null, 415, ref));
        assertEquals(415, new BriefingReplaySettings(source, bundle, artifacts, output.resolve("grants.json"), output.resolve("manifest.json"), sha, "inbox/authored.md", null, 415, "inbox/budget-approved.md").maximumPaidCalls());
        assertThrows(IllegalArgumentException.class, () -> new BriefingReplaySettings(source, bundle, artifacts, output.resolve("grants.json"), output.resolve("manifest.json"), sha, "inbox/authored.md", null, 513, "inbox/budget-approved.md"));
    }
    @Test void detailsAreReconstructedFromPublishedClaimsAndUnicodeSourceSpans() {
        ObjectNode snapshot = StrictJson.newObject(), supplied = input("event"); byte[] bytes = StrictJson.write(supplied); details(supplied, snapshot);
        var detail = snapshot.path("itemDetails").path("event");
        assertEquals("검증 문장", detail.path("claims").get(0).path("text").stringValue());
        assertEquals(evidence().quote(), detail.path("evidence").get(0).path("quote").stringValue());
        assertEquals(evidence().bodySha256(), detail.path("evidence").get(0).path("bodySha256").stringValue());
        assertEquals(18, detail.path("evidence").get(0).path("bodyContext").path("end").intValue());
        assertArrayEquals(bytes, StrictJson.write(supplied));
    }
    @Test void alteredContextOrOffsetCannotBeExposedAsExactSourceText() {
        ObjectNode supplied = input("event"); ((ObjectNode) supplied.path("event").path("evidence").get(0).path("bodyContext")).put("text", "추가 생성 문장");
        assertThrows(IllegalArgumentException.class, () -> details(supplied, StrictJson.newObject()));
        ObjectNode badOffset = context().put("quoteStart", START + 1);
        assertThrows(IllegalArgumentException.class, () -> BriefingPresentationRules.validateContext(StrictJson.Obj.of(badOffset), evidence()));
    }
    @Test void foreignEvidenceAndAdditionalUnpublishedItemsAreRejected() {
        ObjectNode supplied = input("event"); ((ObjectNode) supplied.path("event").path("evidence").get(0)).put("id", "foreign");
        assertThrows(IllegalArgumentException.class, () -> details(supplied, StrictJson.newObject()));
        assertThrows(IllegalArgumentException.class, () -> details(input("event", "unpublished"), StrictJson.newObject()));
    }
    @Test void explicitlyMissingSurroundingContextRetainsTheExactCitation() {
        ObjectNode supplied = input("event"), snapshot = StrictJson.newObject();
        ((ObjectNode) supplied.path("event").path("evidence").get(0)).putNull("bodyContext"); details(supplied, snapshot);
        assertTrue(snapshot.path("itemDetails").path("event").path("evidence").get(0).path("bodyContext").isNull());
    }
    @Test void comparisonUsesOnlyTheTwoPreservedPublicationSets() {
        var previous = new BriefingPresentationRules.Previous(payload("old", "continuing", "gone"), "2026-10-20T00:00:00Z", "2026-10-02T00:20:00Z");
        var current = payload("new", "continuing", "fresh"); var result = BriefingPresentationRules.comparison(current, previous, true);
        assertEquals("continuing", result.path("items").get(0).path("change").stringValue());
        assertEquals("new", result.path("items").get(1).path("change").stringValue());
        assertEquals("dropped", result.path("items").get(2).path("change").stringValue());
        assertTrue(result.path("items").get(2).path("rank").isNull()); assertEquals(2, result.path("items").get(2).path("morningRank").intValue());
        var generic = BriefingPresentationRules.comparison(current, previous, false);
        assertEquals("2026-10-02", generic.path("previousDate").stringValue());
        assertEquals("morning", generic.path("previousEdition").stringValue());
        assertEquals("unavailable", generic.path("forecastEvaluation").path("status").stringValue());
        assertEquals("old", generic.path("previousRoundId").stringValue()); assertEquals("event_identity", generic.path("comparisonBasis").stringValue());
    }
    @Test void suppliedForecastOrMembershipCannotOverrideDerivedComparison() {
        ObjectNode computed = BriefingPresentationRules.comparison(payload("new", "event"), null, false);
        ObjectNode record = StrictJson.newObject(); record.set("previousComparison", computed.deepCopy());
        BriefingPresentationRules.suppliedComparison(StrictJson.Obj.of(record), "previousComparison", computed);
        ((ObjectNode) record.path("previousComparison")).put("status", "available");
        assertThrows(IllegalArgumentException.class, () -> BriefingPresentationRules.suppliedComparison(StrictJson.Obj.of(record), "previousComparison", computed));
    }
    @Test void deterministicSummaryKeepsVerifiedClaimsAndIndicatorDatesWithoutInventingAI() {
        ObjectNode market = market(), snapshot = StrictJson.newObject(); var time = Instant.parse("2026-10-20T00:00:00Z");
        var lineage = BriefingPresentationRules.derivedSummary(snapshot, StrictJson.Obj.of(generation("event")), StrictJson.Obj.of(market), time);
        var summary = snapshot.path("marketSummary"); assertEquals(BriefingPresentationRules.DERIVED_MODE, lineage.path("generationMode").stringValue());
        assertFalse(summary.has("generationMode")); assertFalse(summary.has("scopeNote"));
        assertTrue(summary.path("text").stringValue().contains("검증 문장\nKOSPI 2026-10-01 종가 2500.12pt."));
        assertTrue(summary.path("text").stringValue().contains("원/달러 환율 2026-09-30 은행고시 기준환율 1300원."));
        assertEquals("e1", summary.path("evidenceIds").get(0).stringValue()); assertEquals("event", lineage.path("claims").get(0).path("issueId").stringValue());
        assertFalse(lineage.has("verification"));
        ObjectNode again = StrictJson.newObject(); BriefingPresentationRules.derivedSummary(again, StrictJson.Obj.of(generation("event")), StrictJson.Obj.of(market), time); assertEquals(snapshot, again);
        market.set("summaryResult", StrictJson.newObject());
        assertThrows(IllegalArgumentException.class, () -> BriefingPresentationRules.derivedSummary(StrictJson.newObject(), StrictJson.Obj.of(generation("event")), StrictJson.Obj.of(market), time));
    }
    private static ObjectNode market() {
        ObjectNode value = StrictJson.newObject().putNull("summaryResult").putNull("summaryResultSha256").put("newsResultSha256", "a".repeat(64)).put("marketSnapshotSha256", "b".repeat(64));
        value.putArray("receipts"); ArrayNode indicators = value.putObject("marketSnapshot").putObject("marketVariables").putArray("indicators");
        indicators.addObject().put("id", "kospi").put("status", "ok").put("value", 2500.12).put("observedDate", "2026-10-01").put("valueKind", "close");
        indicators.addObject().put("id", "kosdaq").put("status", "unavailable").putNull("value").putNull("observedDate").putNull("valueKind");
        indicators.addObject().put("id", "usdkrw").put("status", "delayed").put("value", 1300).put("observedDate", "2026-09-30").put("valueKind", "reference"); return value;
    }
}
