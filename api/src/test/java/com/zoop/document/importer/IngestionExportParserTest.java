package com.zoop.document.importer;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.function.Consumer;

import com.zoop.common.json.Text;
import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;

import static com.zoop.document.importer.ExportFixtures.CONTROL_HASH;
import static com.zoop.document.importer.ExportFixtures.CONTROL_TEXT;
import static com.zoop.document.importer.ExportFixtures.EMOJI_HASH;
import static com.zoop.document.importer.ExportFixtures.EMOJI_TEXT;
import static com.zoop.document.importer.ExportFixtures.MIXED_HASH;
import static com.zoop.document.importer.ExportFixtures.MIXED_TEXT;
import static com.zoop.document.importer.ExportFixtures.NFC_HASH;
import static com.zoop.document.importer.ExportFixtures.NFC_TEXT;
import static com.zoop.document.importer.ExportFixtures.NFD_HASH;
import static com.zoop.document.importer.ExportFixtures.NFD_TEXT;
import static com.zoop.document.importer.ExportFixtures.PLAIN_HASH;
import static com.zoop.document.importer.ExportFixtures.PLAIN_TEXT;
import static com.zoop.document.importer.ExportFixtures.documentOf;
import static com.zoop.document.importer.ExportFixtures.export;
import static com.zoop.document.importer.ExportFixtures.observation;
import static com.zoop.document.importer.ExportFixtures.observationOf;
import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class IngestionExportParserTest {
    private final IngestionExportParser parser = new IngestionExportParser();
    private final Observation observation = observation("출처-source", 2, 5, 'a', 'b', 'c');

    private DocumentImportFailure failure(byte[] export) {
        return assertThrows(DocumentImportException.class, () -> parser.parse(export, observation)).failure();
    }

    private DocumentImportFailure failureOf(Consumer<ObjectNode> mutation) {
        ObjectNode export = export(observation, PLAIN_TEXT, PLAIN_HASH);
        mutation.accept(export);
        return failure(ExportFixtures.bytes(export));
    }

    @Test
    void acceptsTheExactExportAndKeepsEveryIdentityVerbatim() {
        VerifiedDocument document = parser.parse(ExportFixtures.bytes(export(observation, MIXED_TEXT, MIXED_HASH)),
                observation);

        assertEquals(observation, document.observation());
        assertEquals("text-" + observation.documentVersion(), document.textArtifactId());
        assertEquals(MIXED_TEXT, document.text());
        assertArrayEquals(MIXED_TEXT.getBytes(StandardCharsets.UTF_8), document.textUtf8());
        assertEquals("authored", document.title());
        assertEquals("https://example.invalid/a", document.url());
        assertEquals(Instant.parse("2026-10-08T00:00:00Z"), document.publishedAt());
        assertEquals(Instant.parse("2026-10-14T01:02:03.456789Z"), document.observedAt());
        assertEquals("operator-grant", document.grantId());
        assertEquals("rights-1", document.grantRevision());
    }

    @Test
    void sourceHashIsPythonCanonicalJsonOfTheText() {
        // (text, sourceHash) pairs computed by Python json.dumps(ensure_ascii=False) + sha256.
        List<String[]> vectors = List.of(
                new String[] {MIXED_TEXT, MIXED_HASH}, new String[] {CONTROL_TEXT, CONTROL_HASH},
                new String[] {PLAIN_TEXT, PLAIN_HASH}, new String[] {NFC_TEXT, NFC_HASH},
                new String[] {NFD_TEXT, NFD_HASH}, new String[] {EMOJI_TEXT, EMOJI_HASH});
        for (String[] vector : vectors) {
            VerifiedDocument document = parser.parse(ExportFixtures.bytes(export(observation, vector[0], vector[1])),
                    observation);
            assertEquals(vector[0], document.text());
        }
    }

    @Test
    void pythonCanonicalFormEscapesOnlyWhatPythonEscapes() {
        assertEquals("\"a\\\"\\\\\\n\\u0001한\uD83D\uDE00\"", Text.pythonJsonString(MIXED_TEXT));
        // DEL, U+2028, U+2029 and "/" stay verbatim; NUL and U+001F become lowercase backslash-u escapes.
        assertEquals("\"\\b\\f\\n\\r\\t\\u0000\\u001f\u007f\u2028\u2029/\"", Text.pythonJsonString(CONTROL_TEXT));
    }

    @Test
    void textIsNeverNormalisedNorReEncoded() {
        assertEquals(DocumentImportFailure.TEXT_HASH_MISMATCH,
                failure(ExportFixtures.bytes(export(observation, NFC_TEXT, NFD_HASH))));
        assertEquals(DocumentImportFailure.TEXT_HASH_MISMATCH,
                failure(ExportFixtures.bytes(export(observation, NFD_TEXT, NFC_HASH))));
        assertEquals(DocumentImportFailure.TEXT_HASH_MISMATCH,
                failure(ExportFixtures.bytes(export(observation, PLAIN_TEXT + " ", PLAIN_HASH))));
        assertEquals(DocumentImportFailure.TEXT_HASH_MISMATCH,
                failure(ExportFixtures.bytes(export(observation, PLAIN_TEXT, "0".repeat(64)))));
    }

    @Test
    void anUnpairedSurrogateHasNoUtf8FormAndIsRefused() {
        assertNull(Text.strictUtf8("a\uD800b"));
        assertNotNull(Text.strictUtf8("a\uD83D\uDE00b"));
        // The JSON reader may or may not pass the escape through; either way the item is refused, never stored.
        ObjectNode export = export(observation, "PLACEHOLDER", PLAIN_HASH);
        byte[] raw = ExportFixtures.JSON.writeValueAsString(export).replace("PLACEHOLDER", "a\\ud800b")
                .getBytes(StandardCharsets.UTF_8);
        assertTrue(Set.of(DocumentImportFailure.TEXT_ENCODING_INVALID, DocumentImportFailure.EXPORT_INVALID)
                .contains(failure(raw)));
    }

    @Test
    void identityMustBeSourceBoundHexAndTheTextArtifactDerivedFromTheVersion() {
        assertEquals(DocumentImportFailure.IDENTITY_UNSUPPORTED,
                failureOf(export -> documentOf(export).put("textArtifactId", "text-" + "f".repeat(64))));
        assertEquals(DocumentImportFailure.IDENTITY_UNSUPPORTED,
                failureOf(export -> documentOf(export).put("textArtifactId", "raw-" + observation.documentVersion())));
        Observation uppercase = new Observation("round-1", "s", 0, 0, "doc-" + "A".repeat(64), "b".repeat(64), "c".repeat(64));
        byte[] export = ExportFixtures.bytes(export(uppercase, PLAIN_TEXT, PLAIN_HASH));
        assertEquals(DocumentImportFailure.IDENTITY_UNSUPPORTED,
                assertThrows(DocumentImportException.class, () -> parser.parse(export, uppercase)).failure());
    }

    @Test
    void theExportMustEchoEveryRequestedSelectorValue() {
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("roundId", "round-2")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("sourceId", "other")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("page", 3)));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("ordinal", 6)));
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                failureOf(e -> observationOf(e).put("documentId", "doc-" + "f".repeat(64))));
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                failureOf(e -> observationOf(e).put("rawVersion", "f".repeat(64))));
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                failureOf(e -> observationOf(e).put("documentVersion", "f".repeat(64))));
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                failureOf(e -> documentOf(e).put("documentId", "doc-" + "f".repeat(64))));
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                failureOf(e -> documentOf(e).put("documentVersion", "f".repeat(64))));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> documentOf(e).put("sourceId", "other")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> documentOf(e).put("inputKind", "summary")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> e.put("schemaVersion", "zoop-ingestion-s2-2")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("page", "2")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("page", 2.0)));
    }

    @Test
    void everyObjectHasExactlyTheLedgerKeys() {
        for (String key : List.of("schemaVersion", "observation", "grant", "document", "locatorMetadata")) {
            assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> e.remove(key)), key);
        }
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> e.put("extra", 1)));
        for (String key : List.of("roundId", "sourceId", "page", "ordinal", "pageId", "observedAt", "documentId", "rawVersion",
                "documentVersion", "url", "title", "publishedAt", "modifiedAt", "sourceRevision", "mediaType")) {
            assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).remove(key)), key);
        }
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("extra", 1)));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> ((ObjectNode) e.get("grant")).remove("revision")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> ((ObjectNode) e.get("grant")).put("extra", 1)));
        for (String key : List.of("documentId", "documentVersion", "sourceId", "textArtifactId", "inputKind", "cleanerVersion",
                "text", "sourceHash", "rawLocators")) {
            assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> documentOf(e).remove(key)), key);
        }
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> documentOf(e).put("extra", 1)));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> e.putNull("locatorMetadata")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> e.putArray("locatorMetadata")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("mediaType", "text/plain")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("modifiedAt", 1)));
    }

    @Test
    void malformedDocumentsAreRefused() {
        byte[] valid = ExportFixtures.bytes(export(observation, PLAIN_TEXT, PLAIN_HASH));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failure(new byte[0]));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failure("[]".getBytes(StandardCharsets.UTF_8)));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failure("not json".getBytes(StandardCharsets.UTF_8)));
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                failure((new String(valid, StandardCharsets.UTF_8) + "{}").getBytes(StandardCharsets.UTF_8)));
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                failure(("{\"schemaVersion\":\"zoop-ingestion-s2-1\",\"schemaVersion\":\"zoop-ingestion-s2-1\"}")
                        .getBytes(StandardCharsets.UTF_8)));
        byte[] invalidUtf8 = new byte[valid.length + 1];
        System.arraycopy(valid, 0, invalidUtf8, 0, valid.length);
        invalidUtf8[valid.length] = (byte) 0xff;
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failure(invalidUtf8));
        // A duplicate key hidden in a nested object.
        String duplicated = new String(valid, StandardCharsets.UTF_8).replace("\"grantId\":\"operator-grant\"",
                "\"grantId\":\"operator-grant\",\"grantId\":\"other\"");
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failure(duplicated.getBytes(StandardCharsets.UTF_8)));
    }

    @Test
    void textMustBeNonEmptyAndBounded() {
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failure(ExportFixtures.bytes(export(observation, "", PLAIN_HASH))));
        String tooLong = "a".repeat(IngestionExportParser.MAX_TEXT_CODE_POINTS + 1);
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                failure(ExportFixtures.bytes(export(observation, tooLong, PLAIN_HASH))));
    }

    @Test
    void publishedAtIsAcceptedOnlyInTheExactLedgerForm() {
        for (String accepted : List.of("2026-10-08T09:00:00+09:00", "2026-10-08T00:00:00Z", "2026-10-08T00:00:00+00:00",
                "2026-10-08T00:00:00.123456+00:00")) {
            ObjectNode export = export(observation, PLAIN_TEXT, PLAIN_HASH);
            observationOf(export).put("publishedAt", accepted);
            assertNotNull(parser.parse(ExportFixtures.bytes(export), observation).publishedAt(), accepted);
        }
        ObjectNode none = export(observation, PLAIN_TEXT, PLAIN_HASH);
        observationOf(none).putNull("publishedAt");
        assertNull(parser.parse(ExportFixtures.bytes(none), observation).publishedAt());

        for (String refused : List.of("2026-10-08", "2026-10-08 09:00:00+09:00", "20261008T090000+0900",
                "2026-10-08T09:00:00", "2026-10-08T09:00:00.1234567+09:00", "2026-10-08T09:00:00.000000001Z",
                "2026-10-08T09:00:00+09:00[Asia/Seoul]", "not-a-time", "", "10000-01-01T00:00:00Z")) {
            assertEquals(DocumentImportFailure.PUBLISHED_AT_UNSUPPORTED,
                    failureOf(e -> observationOf(e).put("publishedAt", refused)), refused);
        }
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("publishedAt", 20261008)));
    }

    @Test
    void observedAtIsRequiredInTheSameForm() {
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("observedAt", "2026-10-14")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).putNull("observedAt")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                failureOf(e -> observationOf(e).put("observedAt", "2026-10-14T01:02:03.1234567+00:00")));
    }

    @Test
    void metadataMustBeStorableAndBounded() {
        assertEquals(DocumentImportFailure.METADATA_UNSUPPORTED, failureOf(e -> observationOf(e).put("title", "a\u0000b")));
        assertEquals(DocumentImportFailure.METADATA_UNSUPPORTED, failureOf(e -> observationOf(e).put("url", "")));
        assertEquals(DocumentImportFailure.METADATA_UNSUPPORTED,
                failureOf(e -> observationOf(e).put("url", "https://example.invalid/\u0000")));
        assertEquals(DocumentImportFailure.METADATA_UNSUPPORTED,
                failureOf(e -> observationOf(e).put("title", "t".repeat(IngestionExportParser.MAX_TITLE_CODE_POINTS + 1))));
        assertEquals(DocumentImportFailure.METADATA_UNSUPPORTED,
                failureOf(e -> observationOf(e).put("url", "u".repeat(IngestionExportParser.MAX_URL_CODE_POINTS + 1))));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).putNull("title")));

        // An empty title is a real value and is kept; Unicode metadata is kept exactly.
        ObjectNode export = export(observation, PLAIN_TEXT, PLAIN_HASH);
        observationOf(export).put("title", "");
        observationOf(export).put("url", "https://example.invalid/한글/\uD83D\uDE00");
        VerifiedDocument document = parser.parse(ExportFixtures.bytes(export), observation);
        assertEquals("", document.title());
        assertEquals("https://example.invalid/한글/\uD83D\uDE00", document.url());
    }
}
