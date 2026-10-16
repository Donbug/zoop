package com.zoop.briefing.input;

import com.zoop.briefing.selection.SelectionInput;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.*;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.json.JsonMapper;
import static org.junit.jupiter.api.Assertions.*;
import static com.zoop.briefing.selection.BriefingCandidateSelectorTest.*;
import static com.zoop.briefing.selection.SelectionInput.*;

class BriefingInputPreparerTest {
    @TempDir Path temp;
    private FileBriefingInputStore store() throws IOException { return new FileBriefingInputStore(temp.resolve("private-input")); }
    private Candidate candidate(String id) {
        var e = evidence("e-" + id, CUTOFF.minusSeconds(5), true, "wire");
        return com.zoop.briefing.selection.BriefingCandidateSelectorTest.candidate(id, local(e.id()), Novelty.NEW_MATERIAL_FACT, e);
    }
    @Test void freezesCompleteProvenanceDecisionsAndExactRequestBytesAndCanReopen() throws Exception {
        var preparer = new BriefingInputPreparer(store());
        String raw = "{ \"jobId\":\"job\", \"input\": {\"한글\":\"a\\nb\"} }\n";
        var market = List.of(new BriefingInputPreparer.MarketObservation("fx", BriefingInputPreparer.Availability.UNAVAILABLE,
            null, null, "provider-not-connected"));
        var prepared = preparer.prepare(input(candidate("a")), market, Map.of("outlook", raw));
        byte[] bytes = Files.readAllBytes(prepared.staged().path());
        assertEquals(prepared.staged().sha256(), FileBriefingInputStore.sha256(bytes));
        assertEquals(bytes.length, prepared.staged().bytes());
        var tree = JsonMapper.builder().build().readTree(bytes);
        assertEquals(raw, tree.path("exactAiRequests").path("outlook").asString());
        assertEquals("g1", tree.path("input").path("context").path("graphVersion").asString());
        assertEquals("text-e-a", tree.path("input").path("candidates").get(0).path("evidence").get(0).path("textArtifactId").asString());
        assertEquals("SELECTED", tree.path("selection").path("audit").get(0).path("disposition").asString());
        assertTrue(tree.path("marketObservations").get(0).path("value").isNull());
        assertEquals(prepared.staged(), new BriefingInputPreparer(store()).prepare(input(candidate("a")), market, Map.of("outlook", raw)).staged());
    }
    @Test void inputOrderAndMutableCallerContainersCannotAlterFrozenContent() throws Exception {
        var list = new ArrayList<>(List.of(candidate("b"), candidate("a")));
        var input = new SelectionInput(context(), true, list);
        list.clear(); assertEquals(2, input.candidates().size());
        var p = new BriefingInputPreparer(store());
        var first = p.prepare(input, List.of(), Map.of());
        var second = p.prepare(input(candidate("a"), candidate("b")), List.of(), Map.of());
        assertEquals(first.staged(), second.staged());
        assertThrows(UnsupportedOperationException.class, () -> input.candidates().clear());
        assertThrows(UnsupportedOperationException.class, () -> first.selection().audit().clear());
    }
    @Test void concurrentWritesPublishOneCompleteFileWithoutOverwriteOrTemporaryLeaks() throws Exception {
        var store = store(); byte[] content = "{\"value\":1}".getBytes(StandardCharsets.UTF_8);
        try (var pool = Executors.newFixedThreadPool(8)) {
            var futures = new ArrayList<java.util.concurrent.Future<FileBriefingInputStore.Staged>>();
            for (int i = 0; i < 32; i++) futures.add(pool.submit(() -> store.put(content)));
            var first = futures.getFirst().get();
            for (var f : futures) assertEquals(first, f.get());
            assertArrayEquals(content, Files.readAllBytes(first.path()));
        }
        try (var files = Files.list(temp.resolve("private-input"))) { assertEquals(1, files.count()); }
    }
    @Test void changedActualRequestBytesCreateDifferentArtifactAndPreserveOldFile() throws Exception {
        var p = new BriefingInputPreparer(store());
        var first = p.prepare(input(candidate("a")), List.of(), Map.of("request", "{\"x\":1}"));
        byte[] original = Files.readAllBytes(first.staged().path());
        var changed = p.prepare(input(candidate("a")), List.of(), Map.of("request", "{ \"x\":1 }"));
        assertNotEquals(first.staged().sha256(), changed.staged().sha256());
        assertArrayEquals(original, Files.readAllBytes(first.staged().path()));
    }
    @Test void sourceFailureAndFutureOrFabricatedMarketValuesAreRejectedBeforeFileWrite() throws Exception {
        var p = new BriefingInputPreparer(store());
        assertThrows(IllegalStateException.class, () -> p.prepare(new SelectionInput(context(), false, List.of()), List.of(), Map.of()));
        var future = new BriefingInputPreparer.MarketObservation("fx", BriefingInputPreparer.Availability.AVAILABLE,
            "1", CUTOFF.plusSeconds(1), "source");
        assertThrows(IllegalArgumentException.class, () -> p.prepare(input(), List.of(future), Map.of()));
        var zero = new BriefingInputPreparer.MarketObservation("fx", BriefingInputPreparer.Availability.UNAVAILABLE, "0", null, null);
        assertThrows(IllegalArgumentException.class, () -> p.prepare(input(), List.of(zero), Map.of()));
        try (var files = Files.list(temp.resolve("private-input"))) { assertEquals(0, files.count()); }
    }
    @Test void exactRequestMustBeSingleCompleteJsonObject() throws Exception {
        var p = new BriefingInputPreparer(store());
        for (String raw : List.of("{} {}", "null", "[]", "{oops}", "{\"x\":1,\"x\":2}"))
            assertThrows(IllegalArgumentException.class, () -> p.prepare(input(), List.of(), Map.of("request", raw)));
    }
    @Test void preciseMarketDecimalAndDateOnlySourceMetadataSurviveFreeze() throws Exception {
        var c = candidate("date"); var e = c.evidence().getFirst();
        var dateOnly = new Evidence(e.id(), e.articleId(), e.articleVersion(), e.textArtifactId(), e.analysisId(),
            PublicationTime.date(java.time.LocalDate.of(2026, 10, 15), java.time.ZoneId.of("Asia/Seoul")),
            CUTOFF, e.checkedScope(), e.verification(), true, true, e.sourceKind(), null);
        var group = new Candidate(c.eventId(), c.eventVersion(), c.canonicalizationRef(), "g1", 2, 3, Check.PASS, false,
            c.novelty(), c.factDeltaRef(), c.factEvidenceIds(), c.impact(), List.of(dateOnly));
        var observation = new BriefingInputPreparer.MarketObservation("precise", BriefingInputPreparer.Availability.AVAILABLE,
            "1.12345678901234567890123456789", CUTOFF, "actual-source");
        var prepared = new BriefingInputPreparer(store()).prepare(input(group), List.of(observation), Map.of());
        String content = Files.readString(prepared.staged().path());
        assertTrue(content.contains("1.12345678901234567890123456789"));
        var tree = JsonMapper.builder().build().readTree(content);
        var published = tree.path("input").path("candidates").get(0).path("evidence").get(0).path("published");
        assertTrue(published.path("exact").isNull());
        assertEquals("2026-10-15", published.path("date").asString());
        assertEquals("Asia/Seoul", published.path("zone").asString());
    }
    @Test void actualRegistrationRequiredAndReceiptMustMatchFrozenBytes() throws Exception {
        var p = new BriefingInputPreparer(store());
        var prepared = p.prepare(input(), List.of(), Map.of());
        var receipt = p.register(prepared, staged -> new BriefingInputPreparer.Registration("owner-artifact-id", staged.sha256(), staged.bytes()));
        assertEquals("owner-artifact-id", receipt.artifactId());
        assertThrows(IOException.class, () -> p.register(prepared, staged -> new BriefingInputPreparer.Registration("fake", "wrong", 0)));
        assertThrows(IOException.class, () -> p.register(prepared, staged -> { throw new IOException("owner unavailable"); }));
        assertThrows(NullPointerException.class, () -> p.register(prepared, null));
    }
    @Test void existingCorruptionOrSymlinkCannotBeSilentlyOverwrittenAndRegistrationDetectsTampering() throws Exception {
        var store = store(); var p = new BriefingInputPreparer(store);
        var prepared = p.prepare(input(), List.of(), Map.of());
        byte[] original = Files.readAllBytes(prepared.staged().path());
        Files.writeString(prepared.staged().path(), "tampered");
        assertThrows(IOException.class, () -> store.put(original));
        assertThrows(IOException.class, () -> p.register(prepared, staged -> fail("must not call registry")));
        Files.delete(prepared.staged().path());
        var outside = temp.resolve("outside"); Files.writeString(outside, "keep");
        Files.createSymbolicLink(prepared.staged().path(), outside);
        assertThrows(IOException.class, () -> store.put(original));
        assertEquals("keep", Files.readString(outside));
    }
    @Test void privatePermissionsAndUnwritableConfigurationFailClosed() throws Exception {
        var staged = store().put("{}".getBytes(StandardCharsets.UTF_8));
        assertEquals(PosixFilePermissions.fromString("rw-------"), Files.getPosixFilePermissions(staged.path()));
        var shared = temp.resolve("shared"); Files.createDirectory(shared);
        Files.setPosixFilePermissions(shared, PosixFilePermissions.fromString("rwxr-xr-x"));
        assertThrows(IOException.class, () -> new FileBriefingInputStore(shared));
        var link = temp.resolve("link"); Files.createSymbolicLink(link, temp.resolve("private-input"));
        assertThrows(IOException.class, () -> new FileBriefingInputStore(link));
    }
}
