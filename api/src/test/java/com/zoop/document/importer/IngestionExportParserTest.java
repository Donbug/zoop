package com.zoop.document.importer;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDate;
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
import static com.zoop.document.importer.ExportFixtures.collected;
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
    void declaredNativeLanguageDoesNotChangeDocumentIdentityOrPublicMetadata() {
        for (String language : List.of("ko", "en-US", "und", "x".repeat(35))) {
            ObjectNode export = export(observation, MIXED_TEXT, MIXED_HASH);
            observationOf(export).put("language", language);
            VerifiedDocument document = parser.parse(ExportFixtures.bytes(export), observation);
            assertEquals(observation, document.observation());
            assertEquals(MIXED_TEXT, document.text());
            assertEquals("authored", document.title());
            assertNull(document.publisher());
        }
        for (String language : List.of("", "k", "x".repeat(36))) {
            assertEquals(DocumentImportFailure.EXPORT_INVALID,
                    failureOf(e -> observationOf(e).put("language", language)));
        }
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).putNull("language")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("language", 7)));
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

    @Test
    void aPublisherIsOptionalAndAbsentOrExplicitNullBothMeanNoneDeclared() {
        ObjectNode absent = export(observation, PLAIN_TEXT, PLAIN_HASH);
        assertTrue(!observationOf(absent).has("publisher"), "the fixture of an older export must not carry the key");
        assertNull(parser.parse(ExportFixtures.bytes(absent), observation).publisher());

        ObjectNode none = export(observation, PLAIN_TEXT, PLAIN_HASH);
        observationOf(none).putNull("publisher");
        assertNull(parser.parse(ExportFixtures.bytes(none), observation).publisher());

        // The key never turns into a source id, host or title guess when it is missing.
        assertNull(parser.parse(ExportFixtures.bytes(collectedExport("instant", "2026-10-14T09:00:00+09:00")), observation).publisher());
    }

    @Test
    void aDeclaredPublisherIsKeptExactlyWithoutTrimmingOrNormalisation() {
        String emoji200 = "\uD83D\uDE00".repeat(IngestionExportParser.MAX_PUBLISHER_CODE_POINTS);
        for (String declared : List.of("합성일보", "  합성일보 \uD83D\uDE00 ", NFD_TEXT, NFC_TEXT, "a b", "a\u00a0b", emoji200)) {
            ObjectNode export = export(observation, PLAIN_TEXT, PLAIN_HASH);
            observationOf(export).put("publisher", declared);
            assertEquals(declared, parser.parse(ExportFixtures.bytes(export), observation).publisher());
        }
        ObjectNode collectedWithPublisher = collectedExport("day", "2026-10-14");
        observationOf(collectedWithPublisher).put("publisher", "합성일보");
        VerifiedDocument document = parser.parse(ExportFixtures.bytes(collectedWithPublisher), observation);
        assertEquals("합성일보", document.publisher());
        assertNotNull(document.collected());
        assertEquals(LocalDate.of(2026, 10, 14), document.publishedDate());
    }

    @Test
    void aPublisherMustBeANonBlankStorableStringOfAtMostTwoHundredCodePoints() {
        String emoji201 = "\uD83D\uDE00".repeat(IngestionExportParser.MAX_PUBLISHER_CODE_POINTS + 1);
        for (String refused : List.of("", " ", "\u00a0\u2003\u2028\u2029", "a\u0000b", "a\tb", "a\nb", "a\rb", "a\u007fb", "a\u0085b",
                "a".repeat(IngestionExportParser.MAX_PUBLISHER_CODE_POINTS + 1), emoji201)) {
            assertEquals(DocumentImportFailure.METADATA_UNSUPPORTED,
                    failureOf(e -> observationOf(e).put("publisher", refused)), "publisher " + refused.length());
        }
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("publisher", 7)));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("publisher", true)));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).putArray("publisher").add("합성일보")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).putObject("publisher")));
    }

    /** The export's bytes with the publisher written as the given RAW JSON string body (escapes included), bypassing any Java string. */
    private byte[] exportWithRawPublisher(String rawJsonStringBody) {
        ObjectNode export = export(observation, PLAIN_TEXT, PLAIN_HASH);
        observationOf(export).put("publisher", "RAWPUBLISHERMARK");
        String json = new String(ExportFixtures.bytes(export), StandardCharsets.UTF_8);
        assertEquals(1, json.split("RAWPUBLISHERMARK", -1).length - 1, "the marker must occur exactly once");
        return json.replace("RAWPUBLISHERMARK", rawJsonStringBody).getBytes(StandardCharsets.UTF_8);
    }

    @Test
    void aLoneSurrogateWrittenAsAJsonEscapeIsNeverStoredAsAPublisher() {
        // Written as escapes inside the JSON text itself (a Java string could not even hold them reliably): a high or low surrogate
        // alone, inside text, in the wrong order, or cut off by the next character. The parser must refuse every one of them, either
        // when the JSON is read (export_invalid) or at the storable check (metadata_unsupported); none may reach a VerifiedDocument.
        for (String raw : List.of("\\ud800", "\\udc00", "a\\ud800b", "a\\udc00b", "\\udc00\\ud800", "\\ud83d", "\\ud83dx",
                "\\ud83d\\ud83d\\ude00", "\\udE00")) {
            byte[] bytes = exportWithRawPublisher(raw);
            DocumentImportFailure refused = failure(bytes);
            assertTrue(refused == DocumentImportFailure.EXPORT_INVALID || refused == DocumentImportFailure.METADATA_UNSUPPORTED,
                    raw + " -> " + refused);
        }
        // Control: the same escapes as a well-formed pair are the emoji, so the refusals above are about the lone surrogate only.
        assertEquals("\uD83D\uDE00", parser.parse(exportWithRawPublisher("\\ud83d\\ude00"), observation).publisher());
        assertEquals("a\uD83D\uDE00b", parser.parse(exportWithRawPublisher("a\\uD83D\\uDE00b"), observation).publisher());
    }

    private ObjectNode collectedExport(String precision, String raw) {
        return collected(export(observation, PLAIN_TEXT, PLAIN_HASH), "news", precision, raw);
    }

    private static ObjectNode collectionOf(ObjectNode export) {
        return (ObjectNode) observationOf(export).get("collection");
    }

    private static ObjectNode publishedOf(ObjectNode export) {
        return (ObjectNode) collectionOf(export).get("published");
    }

    private DocumentImportFailure collectedFailure(String precision, String raw, Consumer<ObjectNode> mutation) {
        ObjectNode export = collectedExport(precision, raw);
        mutation.accept(export);
        return failure(ExportFixtures.bytes(export));
    }

    @Test
    void anAuthoredExportHasNoCollectionFactsAndKeepsItsPrecision() {
        VerifiedDocument dated = parser.parse(ExportFixtures.bytes(export(observation, PLAIN_TEXT, PLAIN_HASH)), observation);
        assertNull(dated.collected());
        assertNull(dated.publishedDate());
        assertEquals("datetime", dated.publicationPrecision());
        ObjectNode none = export(observation, PLAIN_TEXT, PLAIN_HASH);
        observationOf(none).putNull("publishedAt");
        assertEquals("unknown", parser.parse(ExportFixtures.bytes(none), observation).publicationPrecision());
    }

    @Test
    void collectedObservationsKeepEveryDeclaredTimeAtItsOwnPrecisionAndEveryAcquisitionFact() {
        VerifiedDocument instant = parser.parse(ExportFixtures.bytes(collectedExport("instant", "2026-10-14T09:00:00+09:00")), observation);
        assertEquals(Instant.parse("2026-10-14T00:00:00Z"), instant.publishedAt());
        assertNull(instant.publishedDate());
        assertEquals("datetime", instant.publicationPrecision());

        // A calendar date stays a date: never an instant, never a midnight in any zone.
        VerifiedDocument day = parser.parse(ExportFixtures.bytes(collectedExport("day", "2026-10-14")), observation);
        assertNull(day.publishedAt());
        assertEquals(LocalDate.of(2026, 10, 14), day.publishedDate());
        assertEquals("day", day.publicationPrecision());

        // A time without an offset is not given a timezone: the registry stores `unknown`, the declared form is kept in `collected`.
        VerifiedDocument unresolved = parser.parse(ExportFixtures.bytes(collectedExport("unresolved", "2026-10-14T09:30:00")), observation);
        assertNull(unresolved.publishedAt());
        assertNull(unresolved.publishedDate());
        assertEquals("unknown", unresolved.publicationPrecision());
        assertEquals("unresolved", unresolved.collected().declaredPrecision());
        assertEquals("2026-10-14T09:30:00", unresolved.collected().declaredRaw());

        VerifiedDocument unknown = parser.parse(ExportFixtures.bytes(collectedExport("unknown", null)), observation);
        assertEquals("unknown", unknown.publicationPrecision());
        assertNull(unknown.collected().declaredRaw());

        CollectedProvenance facts = day.collected();
        assertEquals("collect-1", facts.collectionId());
        assertEquals(Instant.parse("2026-10-13T23:59:58.123456Z"), facts.fetchedAt());
        assertEquals(200, facts.httpStatus());
        assertEquals("text/html; charset=utf-8", facts.contentType());
        assertEquals("https://example.invalid/a", facts.finalUrl());
        assertEquals("news", facts.documentKind());
        assertEquals("synthetic_loopback", facts.network());
        assertEquals(ExportFixtures.hex64('7'), facts.receiptSha256());
        assertEquals(ExportFixtures.hex64('9'), facts.bodySha256());
    }

    @Test
    void theCollectedFactsAreAClosedConsistentRecord() {
        // The two observation keys exist together or not at all.
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).put("provenance", "collected_http")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, failureOf(e -> observationOf(e).putObject("collection")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> observationOf(e).remove("provenance")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> observationOf(e).remove("collection")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> observationOf(e).put("provenance", "authored_control")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> collectionOf(e).put("provenance", "other")));
        // Closed objects: an unknown key anywhere is refused, not ignored.
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> collectionOf(e).put("extra", 1)));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> publishedOf(e).put("extra", 1)));
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                collectedFailure("day", "2026-10-14", e -> ((ObjectNode) collectionOf(e).get("receipt")).put("extra", 1)));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> collectionOf(e).remove("network")));
        // Values: the body hash must be the export's own raw hash; status, kind, network and times are exact.
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> collectionOf(e).put("bodySha256", ExportFixtures.hex64('8'))));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> ((ObjectNode) collectionOf(e).get("receipt")).put("sha256", "abc")));
        for (int status : new int[] {199, 300, 404, 500}) {
            assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> collectionOf(e).put("httpStatus", status)));
        }
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> collectionOf(e).put("documentKind", "blog")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> collectionOf(e).put("network", "internet")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> collectionOf(e).put("fetchedAt", "2026-10-13T23:59:58")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> collectionOf(e).put("fetchedAt", "2026-10-13")));
        assertEquals(DocumentImportFailure.METADATA_UNSUPPORTED, collectedFailure("day", "2026-10-14", e -> collectionOf(e).put("finalUrl", "")));
    }

    @Test
    void theDeclaredPublicationFieldsMustAgreeWithTheLedgersPublishedAt() {
        // A day is a date and nothing else: no time of day, no other spelling, a real calendar day, no instant beside it.
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                collectedFailure("day", "2026-10-14", e -> observationOf(e).put("publishedAt", "2026-10-14T00:00:00Z")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("day", "2026-10-14", e -> publishedOf(e).put("date", "2026-10-15")));
        assertEquals(DocumentImportFailure.PUBLISHED_AT_UNSUPPORTED, collectedFailure("day", "2026-02-30", e -> { }));
        assertEquals(DocumentImportFailure.PUBLISHED_AT_UNSUPPORTED, collectedFailure("day", "2026-10-14T00:00:00Z", e -> { }));
        assertEquals(DocumentImportFailure.PUBLISHED_AT_UNSUPPORTED, collectedFailure("day", "20261014", e -> { }));
        // An instant must equal the ledger's publishedAt and keep the exact ledger form.
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                collectedFailure("instant", "2026-10-14T09:00:00+09:00", e -> observationOf(e).put("publishedAt", "2026-10-14T00:00:00Z")));
        assertEquals(DocumentImportFailure.PUBLISHED_AT_UNSUPPORTED, collectedFailure("instant", "2026-10-14", e -> { }));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("instant", null, e -> { }));
        // An offset-less time and an undeclared time can never carry a ledger instant.
        assertEquals(DocumentImportFailure.EXPORT_INVALID,
                collectedFailure("unresolved", "2026-10-14T09:30:00", e -> observationOf(e).put("publishedAt", "2026-10-14T09:30:00Z")));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("unknown", "2026-10-14", e -> { }));
        assertEquals(DocumentImportFailure.EXPORT_INVALID, collectedFailure("weekly", "2026-10-14", e -> { }));
    }
}
