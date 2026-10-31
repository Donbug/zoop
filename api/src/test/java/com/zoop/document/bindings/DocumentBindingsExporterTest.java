package com.zoop.document.bindings;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.bindings.BindingSelection.VersionKey;
import com.zoop.document.bindings.DocumentBindingsExporter.Export;
import com.zoop.document.bindings.DocumentBindingsRepository.BindingRow;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** The projection of the registry rows into the AI contract's bindings file: shape, order, determinism, limits and refusals. */
class DocumentBindingsExporterTest {
    static final String DOC_A = "doc-" + "a".repeat(64);
    static final String DOC_B = "doc-" + "b".repeat(64);
    static final String V1 = "1".repeat(64);
    static final String V2 = "2".repeat(64);
    static final String HASH_1 = "c".repeat(64);
    static final String HASH_2 = "d".repeat(64);

    /** The registry as the three reads see it; {@code failure}, when set, is thrown by every read. */
    static final class FakeRepository implements DocumentBindingsRepository {
        final List<BindingRow> rows = new ArrayList<>();
        RuntimeException failure;

        FakeRepository row(String articleId, String version, String status) {
            return row(articleId, version, status, "text-" + version, "extracted_text", HASH_1);
        }

        FakeRepository row(String articleId, String version, String status, String textArtifactId, String kind, String sha) {
            rows.add(new BindingRow(articleId, version, textArtifactId, status, kind, sha));
            return this;
        }

        private void read() {
            if (failure != null) {
                throw failure;
            }
        }

        @Override
        public List<BindingRow> listVersions(boolean availableOnly) {
            read();
            return rows.stream().filter(row -> !availableOnly || "available".equals(row.accessStatus())).toList();
        }

        @Override
        public Map<String, Integer> countExcludedByStatus() {
            read();
            Map<String, Integer> counts = new TreeMap<>();
            for (BindingRow row : rows) {
                if (!"available".equals(row.accessStatus())) {
                    counts.merge(row.accessStatus(), 1, Integer::sum);
                }
            }
            return counts;
        }

        @Override
        public List<BindingRow> findVersions(Collection<VersionKey> keys) {
            read();
            Set<VersionKey> wanted = new HashSet<>(keys);
            return rows.stream().filter(row -> wanted.contains(new VersionKey(row.articleId(), row.version()))).toList();
        }
    }

    private static String binding(String document, String version, String hash) {
        return "{\"articleId\":\"" + document + "\",\"articleVersion\":\"" + version + "\",\"documentId\":\"" + document
                + "\",\"documentVersion\":\"" + version + "\",\"offsetUnit\":\"unicode_code_point\",\"textSha256\":\"" + hash
                + "\"}";
    }

    private static String file(String... bindings) {
        return "{\"bindings\":[" + String.join(",", bindings) + "],\"schemaVersion\":\"zoop-app-document-bindings-1\"}";
    }

    private static String text(Export export) {
        return new String(export.bytes(), StandardCharsets.UTF_8);
    }

    @Test
    void projectsEveryAvailableVersionIntoSortedCanonicalJson() {
        FakeRepository repository = new FakeRepository()
                .row(DOC_B, V1, "available", "text-" + V1, "extracted_text", HASH_2)
                .row(DOC_A, V2, "available", "text-" + V2, "extracted_text", HASH_2)
                .row(DOC_A, V1, "available");

        Export export = new DocumentBindingsExporter(repository).export(DocumentBindingsScope.AVAILABLE, null);

        assertEquals(file(binding(DOC_A, V1, HASH_1), binding(DOC_A, V2, HASH_2), binding(DOC_B, V1, HASH_2)), text(export));
        assertEquals(3, export.count());
        assertEquals(Canonical.sha256(export.bytes()), export.sha256());
        assertEquals(Map.of(), export.excluded());
    }

    @Test
    void theSameRegistryStateAlwaysGivesTheSameBytesWhateverTheRowOrder() {
        FakeRepository ordered = new FakeRepository().row(DOC_A, V1, "available").row(DOC_A, V2, "available")
                .row(DOC_B, V1, "available");
        FakeRepository shuffled = new FakeRepository();
        List<BindingRow> rows = new ArrayList<>(ordered.rows);
        Collections.reverse(rows);
        shuffled.rows.addAll(rows);

        Export first = new DocumentBindingsExporter(ordered).export(DocumentBindingsScope.AVAILABLE, null);
        Export second = new DocumentBindingsExporter(shuffled).export(DocumentBindingsScope.AVAILABLE, null);

        assertArrayEquals(first.bytes(), second.bytes());
        assertEquals(first.sha256(), second.sha256());
    }

    @Test
    void theAvailableScopeLeavesWithdrawnArticlesOutAndCountsThemWhileAllBindsThem() {
        FakeRepository repository = new FakeRepository().row(DOC_A, V1, "available").row(DOC_A, V2, "private")
                .row(DOC_B, V1, "deleted").row(DOC_B, V2, "private");
        DocumentBindingsExporter exporter = new DocumentBindingsExporter(repository);

        Export available = exporter.export(DocumentBindingsScope.AVAILABLE, null);
        Export all = exporter.export(DocumentBindingsScope.ALL, null);

        assertEquals(file(binding(DOC_A, V1, HASH_1)), text(available));
        assertEquals(1, available.count());
        assertEquals(Map.of("deleted", 1, "private", 2), available.excluded());
        assertEquals(4, all.count());
        assertEquals(Map.of(), all.excluded());
        assertTrue(text(all).contains(binding(DOC_B, V1, HASH_1)));
    }

    @Test
    void aSelectionBindsExactlyTheNamedVersionsInSortedOrderUnderTheScope() {
        FakeRepository repository = new FakeRepository().row(DOC_A, V1, "available").row(DOC_A, V2, "available")
                .row(DOC_B, V1, "private");
        DocumentBindingsExporter exporter = new DocumentBindingsExporter(repository);
        BindingSelection selection = new BindingSelection(List.of(new VersionKey(DOC_B, V1), new VersionKey(DOC_A, V2)));

        Export available = exporter.export(DocumentBindingsScope.AVAILABLE, selection);
        Export all = exporter.export(DocumentBindingsScope.ALL, selection);

        assertEquals(file(binding(DOC_A, V2, HASH_1)), text(available));
        assertEquals(Map.of("private", 1), available.excluded());
        assertEquals(file(binding(DOC_A, V2, HASH_1), binding(DOC_B, V1, HASH_1)), text(all));
    }

    @Test
    void aSelectedVersionThatIsNotRegisteredRefusesTheWholeRun() {
        FakeRepository repository = new FakeRepository().row(DOC_A, V1, "available");
        DocumentBindingsExporter exporter = new DocumentBindingsExporter(repository);

        for (VersionKey missing : List.of(new VersionKey(DOC_A, V2), new VersionKey(DOC_B, V1))) {
            BindingSelection selection = new BindingSelection(List.of(new VersionKey(DOC_A, V1), missing));
            DocumentBindingsException refused = assertThrows(DocumentBindingsException.class,
                    () -> exporter.export(DocumentBindingsScope.ALL, selection));
            assertEquals(DocumentBindingsFailure.SELECTION_UNREGISTERED, refused.failure());
        }
    }

    @Test
    void anArtifactThatIsNotExtractedTextRefusesTheExport() {
        FakeRepository repository = new FakeRepository().row(DOC_A, V1, "available")
                .row(DOC_A, V2, "available", "text-" + V2, "graph_snapshot", HASH_1);

        DocumentBindingsException refused = assertThrows(DocumentBindingsException.class,
                () -> new DocumentBindingsExporter(repository).export(DocumentBindingsScope.AVAILABLE, null));

        assertEquals(DocumentBindingsFailure.ARTIFACT_KIND_INVALID, refused.failure());
    }

    @Test
    void aRowThatBreaksTheImportIdentityRuleRefusesTheExport() {
        List<BindingRow> broken = List.of(
                new BindingRow(DOC_A, V1, "text-" + V2, "available", "extracted_text", HASH_1),
                new BindingRow(DOC_A, V1, "other-" + V1, "available", "extracted_text", HASH_1),
                new BindingRow("art-" + "a".repeat(64), V1, "text-" + V1, "available", "extracted_text", HASH_1),
                new BindingRow(DOC_A, "1".repeat(63), "text-" + "1".repeat(63), "available", "extracted_text", HASH_1),
                new BindingRow(DOC_A, V1, "text-" + V1, "available", "extracted_text", "C".repeat(64)),
                new BindingRow(DOC_A, V1, "text-" + V1, "available", "extracted_text", null));
        for (BindingRow row : broken) {
            FakeRepository repository = new FakeRepository();
            repository.rows.add(row);
            DocumentBindingsException refused = assertThrows(DocumentBindingsException.class,
                    () -> new DocumentBindingsExporter(repository).export(DocumentBindingsScope.AVAILABLE, null), row.toString());
            assertEquals(DocumentBindingsFailure.IDENTITY_INVALID, refused.failure(), row.toString());
        }
    }

    @Test
    void aWithdrawnRowOutsideTheScopeIsNotCheckedBecauseItIsNotBound() {
        FakeRepository repository = new FakeRepository().row(DOC_A, V1, "available")
                .row(DOC_A, V2, "deleted", "text-" + V1, "graph_snapshot", "x");

        Export export = new DocumentBindingsExporter(repository).export(DocumentBindingsScope.AVAILABLE, null);

        assertEquals(1, export.count());
        assertEquals(Map.of("deleted", 1), export.excluded());
    }

    @Test
    void aSelectionThatNamesTheSameVersionTwiceIsInvalidBeforeAnyRead() {
        VersionKey key = new VersionKey(DOC_A, V1);

        DocumentBindingsException refused = assertThrows(DocumentBindingsException.class,
                () -> new BindingSelection(List.of(key, key)));

        assertEquals(DocumentBindingsFailure.SELECTION_INVALID, refused.failure());
    }

    private static FakeRepository registryOf(int versions) {
        FakeRepository repository = new FakeRepository();
        for (int index = 0; index < versions; index++) {
            String version = String.format("%064x", index);
            repository.row(DOC_A, version, "available", "text-" + version, "extracted_text", HASH_1);
        }
        return repository;
    }

    /**
     * Both contract limits apply, count first: one binding is 452 canonical bytes, so the byte limit (4,000,000) is the one a
     * real registry meets, at about 8,800 bindings; the entry limit (20,000) is checked before any bytes are built.
     */
    @Test
    void theContractLimitsAreEnforcedEntriesFirstThenBytes() {
        DocumentBindingsException tooMany = assertThrows(DocumentBindingsException.class, () -> new DocumentBindingsExporter(
                registryOf(DocumentBindingsExporter.MAX_BINDINGS + 1)).export(DocumentBindingsScope.AVAILABLE, null));
        assertEquals(DocumentBindingsFailure.BINDINGS_LIMIT, tooMany.failure());

        DocumentBindingsException tooLarge = assertThrows(DocumentBindingsException.class,
                () -> new DocumentBindingsExporter(registryOf(8_900)).export(DocumentBindingsScope.AVAILABLE, null));
        assertEquals(DocumentBindingsFailure.BINDINGS_LIMIT, tooLarge.failure());

        Export largest = new DocumentBindingsExporter(registryOf(8_800)).export(DocumentBindingsScope.AVAILABLE, null);
        assertEquals(8_800, largest.count());
        assertTrue(largest.size() <= DocumentBindingsExporter.MAX_BYTES, "size " + largest.size());
        assertEquals(largest.size(), largest.bytes().length);
    }

    @Test
    void anEmptyRegistryIsAValidEmptyFile() {
        Export export = new DocumentBindingsExporter(new FakeRepository()).export(DocumentBindingsScope.AVAILABLE, null);

        assertEquals(file(), text(export));
        assertEquals(0, export.count());
    }

    @Test
    void aDatabaseFailureIsReportedAsUnavailableWithoutItsMessage() {
        FakeRepository repository = new FakeRepository();
        repository.failure = new DataAccessResourceFailureException("jdbc:postgresql://secret");

        DocumentBindingsException refused = assertThrows(DocumentBindingsException.class,
                () -> new DocumentBindingsExporter(repository).export(DocumentBindingsScope.AVAILABLE, null));

        assertEquals(DocumentBindingsFailure.DATABASE_UNAVAILABLE, refused.failure());
        assertEquals("database_unavailable", refused.getMessage());
    }

    /** What the AI contract's strict Wire model checks (handoff_contracts.Binding/Bindings): exact keys, shapes, uniqueness. */
    @Test
    void theOutputHasExactlyTheContractKeysAndShapes() {
        FakeRepository repository = new FakeRepository().row(DOC_A, V1, "available").row(DOC_B, V2, "available");

        Export export = new DocumentBindingsExporter(repository).export(DocumentBindingsScope.AVAILABLE, null);

        Obj root = StrictJson.parseObject(export.bytes()).exactly(Set.of("schemaVersion", "bindings"));
        assertEquals("zoop-app-document-bindings-1", root.string("schemaVersion"));
        List<Obj> bindings = root.objects("bindings");
        assertEquals(2, bindings.size());
        for (Obj binding : bindings) {
            binding.exactly(Set.of("documentId", "documentVersion", "articleId", "articleVersion", "textSha256", "offsetUnit"));
            assertTrue(DocumentBindingsExporter.ARTICLE_ID.matcher(binding.string("articleId")).matches());
            assertEquals(binding.string("documentId"), binding.string("articleId"));
            assertEquals(binding.string("documentVersion"), binding.string("articleVersion"));
            assertTrue(StrictJson.SHA256.matcher(binding.string("documentVersion")).matches());
            assertTrue(StrictJson.SHA256.matcher(binding.string("textSha256")).matches());
            assertEquals("unicode_code_point", binding.string("offsetUnit"));
        }
    }

    @Test
    void theExportHandsOutCopiesOfItsBytes() {
        Export export = new DocumentBindingsExporter(new FakeRepository().row(DOC_A, V1, "available"))
                .export(DocumentBindingsScope.AVAILABLE, null);

        byte[] first = export.bytes();
        first[0] = '[';

        assertEquals('{', export.bytes()[0]);
    }
}
