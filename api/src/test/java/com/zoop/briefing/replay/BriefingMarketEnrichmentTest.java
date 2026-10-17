package com.zoop.briefing.replay;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.Instant;
import java.time.ZoneId;
import java.util.List;
import java.util.Set;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.*;

/** Entirely authored daily feeds; no database, source fetch, model call, or credentials. */
class BriefingMarketEnrichmentTest {
    @TempDir Path directory;
    private ObjectNode snapshot, record, news;
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");

    @BeforeEach void authoredSnapshot() throws Exception {
        Files.createDirectories(directory.resolve("market/raw"));
        record = StrictJson.newObject().put("roundId", "authored-round").put("date", "2026-10-02")
                .put("edition", "evening").put("cutoff", "2026-10-02T08:30:00Z").put("newsResultSha256", "a".repeat(64));
        snapshot = StrictJson.newObject().put("schemaVersion", "zoop-briefing-market-snapshot-v1").put("scope", "historical_snapshot")
                .put("operationalCollectionGate", false).put("fetchedAt", "2026-10-17T00:00:00Z");
        ObjectNode round = snapshot.putObject("round"); for (String key : List.of("date", "edition", "cutoff")) round.set(key, record.get(key));
        snapshot.putObject("normalization").put("values", "decimal-half-up-2dp").put("change", "difference-of-normalized-values").put("changeRate", "change/baseline");
        snapshot.putArray("rawRefs"); snapshot.putArray("indicatorBindings");
        ObjectNode variables = snapshot.putObject("marketVariables").put("status", "available").put("referenceAt", record.path("cutoff").stringValue())
                .put("rateCutoffAt", record.path("cutoff").stringValue()).put("collectedAt", "2026-10-17T00:00:00Z");
        ArrayNode indicators = variables.putArray("indicators");
        ObjectNode kospi = indicator("kospi", "ok", 100.0, "2026-10-02", "yahoo");
        kospi.putObject("baseline").put("date", "2026-10-01").put("value", 90.0).putNull("at"); kospi.put("change", 10.0).put("changeRate", 10.0 / 90.0);
        indicators.add(kospi); indicators.add(indicator("kosdaq", "unavailable", null, null, null));
        ObjectNode fx = indicator("usdkrw", "delayed", 1300.0, "2026-10-01", "naver");
        fx.putObject("baseline").put("date", "2026-09-30").put("value", 1290.0).putNull("at"); fx.put("change", 10.0).put("changeRate", 10.0 / 1290.0); indicators.add(fx);
        ObjectNode yahoo = StrictJson.newObject(); ObjectNode feed = yahoo.putObject("chart").putArray("result").addObject();
        feed.putObject("meta").put("symbol", "^KS11"); ArrayNode dates = feed.putArray("timestamp");
        for (String date : List.of("2026-10-01", "2026-10-02", "2026-10-05")) dates.add(LocalDate.parse(date).atTime(9, 0).atZone(KST).toEpochSecond());
        ArrayNode closes = feed.putObject("indicators").putArray("quote").addObject().putArray("close"); closes.add(90.0).add(100.004).add(110.0);
        String yahooSha = raw(StrictJson.write(yahoo)); addRefAndBinding("kospi", yahooSha, 1, "2026-10-02", "2026-10-02T06:30:00Z", "close", "session_close");
        ArrayNode fxRows = StrictJson.newArray(); fxRows.addObject().put("localTradedAt", "2026-10-02").put("closePrice", "1,320.00");
        fxRows.addObject().put("localTradedAt", "2026-10-01").put("closePrice", "1,300.00"); fxRows.addObject().put("localTradedAt", "2026-09-30").put("closePrice", "1,290.00");
        String fxSha = raw(StrictJson.write(fxRows)); addRefAndBinding("usdkrw", fxSha, 1, "2026-10-01", "2026-10-01T15:00:00Z", "closePrice", "day");
        record.set("marketSnapshot", snapshot);
        news = StrictJson.newObject().put("roundId", "authored-round").put("date", "2026-10-02").put("edition", "evening").put("resultSha256", "a".repeat(64));
        news.putObject("window").put("to", record.path("cutoff").stringValue());
        news.putArray("selected").addObject().putArray("sources").addObject().put("evidenceId", "authored-evidence");
    }

    private static ObjectNode indicator(String id, String status, Double value, String date, String provider) {
        ObjectNode valueNode = StrictJson.newObject().put("id", id).put("label", id).put("unit", "usdkrw".equals(id) ? "KRW" : "pt").put("status", status)
                .putNull("observedAt").putNull("baseline").putNull("change").putNull("changeRate").putNull("source").putNull("reasonCode").putNull("reason");
        if (value == null) valueNode.putNull("value").putNull("valueKind").putNull("observedDate").put("reason", "Authored source missing").put("reasonCode", "no_data");
        else {
            valueNode.put("value", value).put("valueKind", "close").put("observedDate", date);
            valueNode.putObject("source").put("provider", provider).put("name", "Authored source").put("symbol", id).put("official", false)
                    .putNull("delayNote").put("url", "https://example.invalid/authored");
        }
        return valueNode;
    }

    private String raw(byte[] bytes) throws Exception {
        String sha = Canonical.sha256(bytes); Files.write(directory.resolve("market/raw/" + sha + ".bin"), bytes); return sha;
    }
    private void addRefAndBinding(String id, String sha, int index, String date, String upper, String field, String precision) throws Exception {
        ((ArrayNode) snapshot.get("rawRefs")).addObject().put("source", "authored-" + id).put("url", "https://example.invalid/" + id)
                .put("sha256", sha).put("bytes", Files.size(directory.resolve("market/raw/" + sha + ".bin"))).putArray("indicatorIds").add(id);
        ((ArrayNode) snapshot.get("indicatorBindings")).addObject().put("id", id).put("rawSha256", sha).put("sourceDate", date)
                .put("availabilityUpperBound", upper).put("sourceRowIndex", index).put("field", field).put("precision", precision);
    }
    private ObjectNode card(String id) {
        return (ObjectNode) snapshot.path("marketVariables").path("indicators").values().stream().filter(value -> id.equals(value.path("id").stringValue())).findFirst().orElseThrow();
    }
    private void validateSnapshot() { BriefingReplayImporter.validateMarketSnapshot(StrictJson.Obj.of(snapshot), StrictJson.Obj.of(record)); }
    private void validateRaw() { BriefingReplayImporter.validateMarketRawValues(StrictJson.Obj.of(snapshot), directory); }

    private ObjectNode summary(boolean pass) {
        ObjectNode summary = StrictJson.newObject().put("generatedAt", "2026-10-17T00:10:00Z").put("scopeNote", "Only authored inputs; no causality claim.");
        ArrayNode claims = summary.putArray("claims");
        claims.addObject().put("claimId", "market:claim:0").put("text", "Authored company announced a plan.").putArray("evidenceIds").add("authored-evidence");
        ((ObjectNode) claims.get(0)).putArray("indicatorIds");
        claims.addObject().put("claimId", "market:claim:1").put("text", "Authored KOSPI close was 100.").putArray("indicatorIds").add("kospi");
        ((ObjectNode) claims.get(1)).putArray("evidenceIds");
        if (pass) summary.put("text", "Authored company announced a plan.\nAuthored KOSPI close was 100.\nOnly authored inputs; no causality claim.")
                .put("resultVersion", "authored-version").putObject("summary");
        else summary.putNull("text").putNull("resultVersion").putNull("summary");
        ArrayNode checks = summary.putObject("verification").put("status", pass ? "PASS" : "WITHHELD").putArray("checks");
        for (int index = 0; index < 2; index++) checks.addObject().put("targetId", "market:claim:" + index).put("verdict", pass ? "SUPPORTED" : "UNSUPPORTED")
                .put("noUnsupportedNumbers", true).put("noUnsupportedCausality", true).put("temporalAppropriate", true).put("noInvestmentAdvice", true).put("reason", "Authored check");
        return summary;
    }
    private void validateSummary(ObjectNode value) { BriefingReplayImporter.validateMarketSummary(StrictJson.Obj.of(value), StrictJson.Obj.of(news), StrictJson.Obj.of(snapshot)); }

    @Test void actualNormalizedRawValuesAndPartialMissingIndicatorAreAccepted() {
        assertEquals(Set.of("kospi", "usdkrw"), BriefingReplayImporter.validateMarketSnapshot(StrictJson.Obj.of(snapshot), StrictJson.Obj.of(record))); validateRaw();
    }
    @Test void emptyFailedTransportReceiptPreservesMissingValueWithoutInventingZero() throws Exception {
        String sha = raw(new byte[0]);
        ObjectNode failure = ((ArrayNode) snapshot.get("rawRefs")).addObject().put("source", "yahoo")
                .put("url", "https://example.invalid/unreachable").put("sha256", sha).put("bytes", 0).put("httpStatus", 0);
        failure.putArray("indicatorIds").add("kosdaq"); card("kosdaq").put("status", "failed").put("reasonCode", "temporary_failure");
        validateSnapshot(); validateRaw();
        assertTrue(card("kosdaq").path("value").isNull()); assertTrue(card("kosdaq").path("change").isNull());
        assertEquals(0, Files.size(directory.resolve("market/raw/" + sha + ".bin")));
        failure.put("httpStatus", 200); assertThrows(IllegalArgumentException.class, this::validateSnapshot);
        failure.remove("httpStatus"); assertThrows(IllegalArgumentException.class, this::validateSnapshot);
    }
    @Test void unavailableIsNotConvertedToZeroButGenuineZeroIsAllowed() {
        card("kosdaq").put("value", 0.0); assertThrows(IllegalArgumentException.class, this::validateSnapshot);
        card("kosdaq").putNull("value"); card("kospi").put("value", 0.0); validateSnapshot();
        assertThrows(IllegalArgumentException.class, this::validateRaw);
    }
    @Test void morningCannotUseSameDayClosingValue() {
        record.put("edition", "morning").put("cutoff", "2026-10-02T00:20:00Z");
        ((ObjectNode) snapshot.get("round")).put("edition", "morning").put("cutoff", "2026-10-02T00:20:00Z");
        ((ObjectNode) snapshot.get("marketVariables")).put("referenceAt", "2026-10-02T00:20:00Z").put("rateCutoffAt", "2026-10-02T00:20:00Z");
        assertThrows(IllegalArgumentException.class, this::validateSnapshot); assertThrows(IllegalArgumentException.class, this::validateRaw);
    }
    @Test void futureTimeAndFutureDateAreRejected() {
        card("kospi").put("observedAt", "2026-10-02T09:00:00Z"); assertThrows(IllegalArgumentException.class, this::validateSnapshot);
        card("kospi").putNull("observedAt").put("observedDate", "2026-10-03"); assertThrows(IllegalArgumentException.class, this::validateSnapshot);
    }
    @Test void changedRawBytesFailWithoutRepairingThem() throws Exception {
        String sha = snapshot.path("rawRefs").get(0).path("sha256").stringValue(); Path file = directory.resolve("market/raw/" + sha + ".bin");
        Files.writeString(file, "changed"); assertThrows(IllegalArgumentException.class, this::validateRaw); assertEquals("changed", Files.readString(file));
    }
    @Test void swappedSourceRowOrValueIsRejected() {
        card("kospi").put("value", 101.0); assertThrows(IllegalArgumentException.class, this::validateRaw); card("kospi").put("value", 100.0);
        ((ObjectNode) snapshot.path("indicatorBindings").get(0)).put("sourceRowIndex", 0); assertThrows(IllegalArgumentException.class, this::validateRaw);
    }
    @Test void baselineAndCalculatedChangesMustMatchRawFeed() {
        ((ObjectNode) card("kospi").get("baseline")).put("value", 89.0); assertThrows(IllegalArgumentException.class, this::validateRaw);
        ((ObjectNode) card("kospi").get("baseline")).put("value", 90.0); card("kospi").put("changeRate", 0.2); assertThrows(IllegalArgumentException.class, this::validateRaw);
    }
    @Test void fxDailyFinalValueCannotUseSameDayRateEvenInEvening() {
        ((ObjectNode) snapshot.path("indicatorBindings").get(1)).put("sourceRowIndex", 0).put("sourceDate", "2026-10-02").put("availabilityUpperBound", "2026-10-02T15:00:00Z");
        card("usdkrw").put("observedDate", "2026-10-02").put("value", 1320.0); assertThrows(IllegalArgumentException.class, this::validateRaw);
    }
    @Test void summaryRequiresCompleteIndependentChecksAndExactNewsReferences() {
        ObjectNode summary = summary(true); validateSummary(summary);
        ((ArrayNode) summary.path("claims").get(0).path("evidenceIds")).add("foreign-news"); assertThrows(IllegalArgumentException.class, () -> validateSummary(summary));
        ObjectNode wrongCheck = summary(true); ((ObjectNode) wrongCheck.path("verification").path("checks").get(0)).put("targetId", "another-round");
        assertThrows(IllegalArgumentException.class, () -> validateSummary(wrongCheck));
    }
    @Test void missingIndicatorAndUnverifiedTextCannotBeDisclosed() {
        ObjectNode missing = summary(true); ((ArrayNode) missing.path("claims").get(1).path("indicatorIds")).add("kosdaq");
        assertThrows(IllegalArgumentException.class, () -> validateSummary(missing));
        ObjectNode extra = summary(true); extra.put("text", "An unverified outlook was appended."); assertThrows(IllegalArgumentException.class, () -> validateSummary(extra));
    }
    @Test void withheldResultNeverExposesDraftTextAndApplicationDoesNotMutateRecord() {
        ObjectNode withheld = summary(false); validateSummary(withheld); record.set("summaryResult", withheld);
        record.put("contextSha256", "b".repeat(64)).put("marketSnapshotSha256", "c".repeat(64)).putObject("context");
        ObjectNode payload = StrictJson.newObject(), stored = StrictJson.newObject(); payload.putObject("metadata").putArray("failures");
        byte[] before = StrictJson.write(record); BriefingReplayImporter.applyMarketEnrichment(payload, stored, StrictJson.Obj.of(record));
        assertArrayEquals(before, StrictJson.write(record)); assertEquals("unavailable", stored.path("marketSummary").path("status").stringValue());
        assertFalse(stored.path("marketSummary").has("text")); assertTrue(payload.path("marketVariables").equals(snapshot.path("marketVariables")));
    }
    @Test void differentRoundAndNewsResultHashFailBeforeAnyArtifactRead() {
        record.put("newsResultSha256", "d".repeat(64)); assertThrows(IllegalArgumentException.class,
                () -> BriefingReplayImporter.validateMarketRecord(StrictJson.Obj.of(record), StrictJson.Obj.of(news), "inbox/authored.md", directory));
    }
    @Test void enrichmentPublicationUsesSavedSummaryFetchAndReceiptTimesDeterministically() {
        record.set("summaryResult", summary(true));
        record.putArray("receipts").addObject().put("finishedAt", "2026-10-17T00:11:00Z");
        Instant newsGenerated = Instant.parse("2026-10-16T00:00:00Z");
        byte[] before = StrictJson.write(record);
        var first = BriefingReplayImporter.marketPublicationTimes(newsGenerated, StrictJson.Obj.of(record));
        assertEquals(Instant.parse("2026-10-17T00:10:00Z"), first.generatedAt());
        assertEquals(Instant.parse("2026-10-17T00:11:00Z"), first.publishedAt());
        assertEquals(first.publishedAt(), first.artifactCreatedAt());
        assertEquals(first, BriefingReplayImporter.marketPublicationTimes(newsGenerated, StrictJson.Obj.of(record)));
        assertArrayEquals(before, StrictJson.write(record));
    }
    @Test void missingSummaryStillPublishesAfterMarketFetchAndNeverBackdatesNewerNews() {
        record.putNull("summaryResult"); record.putArray("receipts").addObject().put("status", "unknown");
        Instant oldNews = Instant.parse("2026-10-16T00:00:00Z");
        var missing = BriefingReplayImporter.marketPublicationTimes(oldNews, StrictJson.Obj.of(record));
        assertEquals(oldNews, missing.generatedAt()); assertEquals(Instant.parse("2026-10-17T00:00:00Z"), missing.publishedAt());
        Instant newerNews = Instant.parse("2026-10-18T00:00:00Z");
        var newer = BriefingReplayImporter.marketPublicationTimes(newerNews, StrictJson.Obj.of(record));
        assertEquals(newerNews, newer.generatedAt()); assertEquals(newerNews, newer.publishedAt());
    }
    @Test void withheldSummaryProducerTimeIsPreservedAndMalformedReceiptTimeCannotBeGuessed() {
        record.set("summaryResult", summary(false)); record.putArray("receipts");
        var times = BriefingReplayImporter.marketPublicationTimes(Instant.parse("2026-10-16T00:00:00Z"), StrictJson.Obj.of(record));
        assertEquals(Instant.parse("2026-10-17T00:10:00Z"), times.generatedAt());
        ((ArrayNode) record.get("receipts")).addObject().put("finishedAt", "not-a-timestamp");
        assertThrows(java.time.format.DateTimeParseException.class, () -> BriefingReplayImporter.marketPublicationTimes(
                Instant.parse("2026-10-16T00:00:00Z"), StrictJson.Obj.of(record)));
    }
}
