package com.zoop.document.importer;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.DateTimeException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.HexFormat;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.common.json.StrictJson;
import com.zoop.common.json.Text;
import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import com.zoop.document.service.ArticleKind;

/**
 * Validates one S2-1 {@code zoop-ai-ingest export} document against the exact observation the operator asked for.
 *
 * <p>The contract is closed: every object has exactly the keys the ledger emits, the selector values echo the request,
 * the identity is the source-bound S2-1 identity ({@code textArtifactId == "text-" + documentVersion}), and the text
 * must hash to the ledger's {@code sourceHash} (SHA-256 of Python {@code json.dumps(text, ensure_ascii=False)}), so a
 * text that was altered, re-normalised or re-encoded anywhere on the way is refused. Time values are accepted only in
 * the exact, unambiguous form the ledger writes (ISO-8601 with an offset, at most microseconds); anything Python might
 * read differently is refused instead of guessed. Nothing is printed: failures are codes.
 */
public final class IngestionExportParser {
    public static final String SCHEMA_VERSION = "zoop-ingestion-s2-1";
    public static final int MAX_TEXT_CODE_POINTS = 500_000;
    static final int MAX_TITLE_CODE_POINTS = 2_000;
    static final int MAX_URL_CODE_POINTS = 8_000;
    private static final int MAX_GRANT_CODE_POINTS = 1_000;

    private static final Pattern DOCUMENT_ID = Pattern.compile("doc-[0-9a-f]{64}");
    private static final Set<String> TOP = Set.of("schemaVersion", "observation", "grant", "document", "locatorMetadata");
    private static final Set<String> OBSERVATION = Set.of("roundId", "sourceId", "page", "ordinal", "pageId", "observedAt",
            "documentId", "rawVersion", "documentVersion", "url", "title", "publishedAt", "modifiedAt", "sourceRevision",
            "mediaType");
    private static final Set<String> GRANT = Set.of("grantId", "revision");
    private static final Set<String> DOCUMENT = Set.of("documentId", "documentVersion", "sourceId", "textArtifactId",
            "inputKind", "cleanerVersion", "text", "sourceHash", "rawLocators");
    private static final Set<String> MEDIA_TYPES = Set.of("text/html", "application/pdf");
    /** Present together, and only for an observation collected over HTTP; an authored export has neither key. */
    private static final Set<String> COLLECTED_KEYS = Set.of("provenance", "collection");
    private static final Set<String> COLLECTION = Set.of("provenance", "collectionId", "receipt", "fetchedAt", "finalUrl",
            "httpStatus", "contentType", "bodySha256", "documentKind", "network", "published");
    private static final Set<String> FILE_REF = Set.of("file", "sha256");
    private static final Set<String> PUBLISHED = Set.of("raw", "precision", "date", "basis");
    private static final Pattern CALENDAR_DATE = Pattern.compile("[0-9]{4}-[0-9]{2}-[0-9]{2}");
    private static final int MAX_COLLECTION_CODE_POINTS = 200;

    public VerifiedDocument parse(byte[] export, Observation expected) {
        try {
            return verify(StrictJson.parseObject(export), expected);
        } catch (StrictJson.Malformed malformed) {
            throw failure(DocumentImportFailure.EXPORT_INVALID);
        }
    }

    private static VerifiedDocument verify(StrictJson.Obj root, Observation expected) {
        root.exactly(TOP);
        require(SCHEMA_VERSION.equals(root.string("schemaVersion")));
        StrictJson.Obj observation = root.object("observation").keys(OBSERVATION, COLLECTED_KEYS);
        require(observation.has("provenance") == observation.has("collection"));
        StrictJson.Obj grant = root.object("grant").exactly(GRANT);
        StrictJson.Obj document = root.object("document").exactly(DOCUMENT);
        root.object("locatorMetadata");

        // The export must be the very observation that was asked for, and the document must belong to it.
        require(expected.roundId().equals(observation.string("roundId")));
        require(expected.sourceId().equals(observation.string("sourceId")));
        require(observation.count("page") == expected.page());
        require(observation.count("ordinal") == expected.ordinal());
        require(expected.documentId().equals(observation.string("documentId")));
        require(expected.rawVersion().equals(observation.string("rawVersion")));
        require(expected.documentVersion().equals(observation.string("documentVersion")));
        require(expected.documentId().equals(document.string("documentId")));
        require(expected.documentVersion().equals(document.string("documentVersion")));
        require(expected.sourceId().equals(document.string("sourceId")));
        require("body".equals(document.string("inputKind")));
        require(!document.string("cleanerVersion").isEmpty());
        document.array("rawLocators");
        observation.string("pageId");
        observation.stringOrNull("modifiedAt");
        observation.stringOrNull("sourceRevision");
        require(MEDIA_TYPES.contains(observation.string("mediaType")));

        String grantId = bounded(grant.string("grantId"), MAX_GRANT_CODE_POINTS);
        String grantRevision = bounded(grant.string("revision"), MAX_GRANT_CODE_POINTS);

        // Identity: source-bound, global, lowercase hex, and the text artifact is derived from the version.
        String textArtifactId = document.string("textArtifactId");
        if (!DOCUMENT_ID.matcher(expected.documentId()).matches()
                || !StrictJson.SHA256.matcher(expected.documentVersion()).matches()
                || !textArtifactId.equals("text-" + expected.documentVersion())) {
            throw failure(DocumentImportFailure.IDENTITY_UNSUPPORTED);
        }

        String text = document.string("text");
        int codePoints = Text.codePoints(text);
        require(codePoints >= 1 && codePoints <= MAX_TEXT_CODE_POINTS);
        String sourceHash = document.string("sourceHash");
        require(StrictJson.SHA256.matcher(sourceHash).matches());
        byte[] textUtf8 = Text.strictUtf8(text);
        if (textUtf8 == null) {
            throw failure(DocumentImportFailure.TEXT_ENCODING_INVALID);
        }
        byte[] canonical = Text.strictUtf8(Text.pythonJsonString(text));
        if (canonical == null || !sha256(canonical).equals(sourceHash)) {
            throw failure(DocumentImportFailure.TEXT_HASH_MISMATCH);
        }

        Instant observedAt = timestamp(observation.string("observedAt"), DocumentImportFailure.EXPORT_INVALID);
        CollectedProvenance collected = observation.has("provenance")
                ? collected(observation, root.object("locatorMetadata")) : null;

        Instant publishedAt = null;
        LocalDate publishedDate = null;
        String precision = "unknown";
        if (collected == null) {
            if (!observation.isNull("publishedAt")) {
                publishedAt = timestamp(observation.string("publishedAt"), DocumentImportFailure.PUBLISHED_AT_UNSUPPORTED);
                precision = "datetime";
            }
        } else {
            // The declared classification and the ledger's publishedAt must agree; a date is never widened to a midnight.
            switch (collected.declaredPrecision()) {
                case "instant" -> {
                    require(!observation.isNull("publishedAt")
                            && collected.declaredRaw().equals(observation.string("publishedAt")));
                    publishedAt = timestamp(collected.declaredRaw(), DocumentImportFailure.PUBLISHED_AT_UNSUPPORTED);
                    precision = "datetime";
                }
                case "day" -> {
                    require(observation.isNull("publishedAt"));
                    publishedDate = calendarDate(collected.declaredRaw());
                    precision = "day";
                }
                case "unresolved", "unknown" -> require(observation.isNull("publishedAt"));
                default -> throw failure(DocumentImportFailure.EXPORT_INVALID);
            }
        }

        String title = observation.string("title");
        String url = observation.string("url");
        if (Text.codePoints(title) > MAX_TITLE_CODE_POINTS || url.isEmpty()
                || Text.codePoints(url) > MAX_URL_CODE_POINTS || !Text.storable(title) || !Text.storable(url)) {
            throw failure(DocumentImportFailure.METADATA_UNSUPPORTED);
        }
        return new VerifiedDocument(expected, textArtifactId, text, textUtf8, title, url, publishedAt, publishedDate, precision,
                observedAt, grantId, grantRevision, collected, document.node());
    }

    /**
     * The acquisition facts of a collected observation, validated in the closed form the ledger writes. The body hash must be
     * the export's own raw hash, the declared publication fields must be mutually consistent, and every time keeps the
     * ledger's exact form. These facts are an operator-owned, unsigned record, never proof of a fetch or a license.
     */
    private static CollectedProvenance collected(StrictJson.Obj observation, StrictJson.Obj metadata) {
        require(CollectedProvenance.PROVENANCE.equals(observation.string("provenance")));
        StrictJson.Obj collection = observation.object("collection").exactly(COLLECTION);
        require(CollectedProvenance.PROVENANCE.equals(collection.string("provenance")));
        StrictJson.Obj receipt = collection.object("receipt").exactly(FILE_REF);
        bounded(receipt.string("file"), 500);
        String receiptSha256 = receipt.string("sha256");
        String bodySha256 = collection.string("bodySha256");
        require(StrictJson.SHA256.matcher(receiptSha256).matches() && StrictJson.SHA256.matcher(bodySha256).matches());
        require(bodySha256.equals(metadata.string("rawHash")));
        int status = collection.count("httpStatus");
        require(status >= 200 && status <= 299);
        Instant fetchedAt = timestamp(collection.string("fetchedAt"), DocumentImportFailure.EXPORT_INVALID);
        String finalUrl = collection.string("finalUrl");
        String contentType = collection.string("contentType");
        if (finalUrl.isEmpty() || Text.codePoints(finalUrl) > MAX_URL_CODE_POINTS || !Text.storable(finalUrl)
                || Text.codePoints(contentType) > MAX_COLLECTION_CODE_POINTS || !Text.storable(contentType)) {
            throw failure(DocumentImportFailure.METADATA_UNSUPPORTED);
        }
        String network = collection.string("network");
        require(network.equals("external") || network.equals("synthetic_loopback"));
        String kind = collection.string("documentKind");
        require(ArticleKind.fromWire(kind).isPresent());
        StrictJson.Obj published = collection.object("published").exactly(PUBLISHED);
        String precision = published.string("precision");
        String raw = published.stringOrNull("raw");
        String date = published.stringOrNull("date");
        boolean consistent = switch (precision) {
            case "instant" -> raw != null && date == null;
            case "day" -> raw != null && raw.equals(date);
            case "unresolved" -> raw != null && date == null;
            case "unknown" -> raw == null && date == null;
            default -> false;
        };
        require(consistent);
        return new CollectedProvenance(bounded(collection.string("collectionId"), 100), receiptSha256, bodySha256, fetchedAt,
                finalUrl, status, contentType, network, kind, precision, raw,
                bounded(published.string("basis"), MAX_COLLECTION_CODE_POINTS));
    }

    /** {@code YYYY-MM-DD} only: no time, no zone, no other spelling, and a real calendar day. */
    private static LocalDate calendarDate(String value) {
        try {
            if (value == null || !CALENDAR_DATE.matcher(value).matches()) {
                throw failure(DocumentImportFailure.PUBLISHED_AT_UNSUPPORTED);
            }
            return LocalDate.parse(value);
        } catch (DateTimeException error) {
            throw failure(DocumentImportFailure.PUBLISHED_AT_UNSUPPORTED);
        }
    }

    /**
     * ISO-8601 date-time with an offset ({@code Z} or {@code +hh:mm}) at no finer than microseconds, years 1 to 9999.
     * Python 3.12 also reads a space separator and basic format and truncates longer fractions; none of that is accepted.
     */
    static Instant timestamp(String value, DocumentImportFailure code) {
        try {
            OffsetDateTime parsed = OffsetDateTime.parse(value);
            if (parsed.getNano() % 1_000 != 0 || parsed.getYear() < 1 || parsed.getYear() > 9_999) {
                throw failure(code);
            }
            return parsed.toInstant();
        } catch (DateTimeException error) {
            throw failure(code);
        }
    }

    private static String bounded(String value, int maxCodePoints) {
        require(!value.isEmpty() && Text.codePoints(value) <= maxCodePoints);
        return value;
    }

    private static void require(boolean condition) {
        if (!condition) {
            throw failure(DocumentImportFailure.EXPORT_INVALID);
        }
    }

    private static String sha256(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 is unavailable", error);
        }
    }

    private static DocumentImportException failure(DocumentImportFailure failure) {
        return new DocumentImportException(failure);
    }
}
