package com.zoop.document.importer;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Synthetic S2-1 export documents in the exact shape of {@code zoop-ai-ingest export}. The source hashes of the named
 * texts were computed once by Python ({@code sha256(json.dumps(text, ensure_ascii=False))}), independently of the code
 * under test.
 */
final class ExportFixtures {
    static final JsonMapper JSON = JsonMapper.builder().build();

    /** {@code a"\} LF U+0001 Hangul and a non-BMP emoji. */
    static final String MIXED_TEXT = "a\"\\\n\u0001한\uD83D\uDE00";
    static final String MIXED_HASH = "e58dd1d218725b581e8b9f0b17fab92f8d3fd317874f43285fede75d3a3f3a38";
    /** Every short escape, U+0000, U+001F, DEL, U+2028, U+2029 and a slash. */
    static final String CONTROL_TEXT = "\b\f\n\r\t\u0000\u001f\u007f\u2028\u2029/";
    static final String CONTROL_HASH = "31a91b452e3fb04aeb7e6c09a0d35b6ceb24792b6d1e7d21ad775b6880b8f5b1";
    static final String PLAIN_TEXT = "삼성전자 실적 발표 &amp; \"인용\" \\ 경로";
    static final String PLAIN_HASH = "367337e3e89d5713cd5def4daafa0dbfdabcc1ac2d058e420c89004482ab3f59";
    /** One precomposed Hangul syllable and its decomposed form: different strings, different hashes. */
    static final String NFC_TEXT = "\uac00";
    static final String NFC_HASH = "c04fdbc8c7a508c92af13e168e01bcdb441dd488a6e3aabe2aa9a4df5546ce50";
    static final String NFD_TEXT = "\u1100\u1161";
    static final String NFD_HASH = "637897087882e6695a28805f393e45120981e6f4e5bda1b655f9b09e539e96d9";
    /** Grinning face and the Korean flag (two regional indicators). */
    static final String EMOJI_TEXT = "\uD83D\uDE00\uD83C\uDDF0\uD83C\uDDF7";
    static final String EMOJI_HASH = "c6f88c3b966382354601aa022ec6444e092b246e6b47c149916870acf6f4ca83";

    static final String OBSERVED_AT = "2026-10-14T01:02:03.456789+00:00";
    static final String PUBLISHED_AT = "2026-10-08T09:00:00+09:00";

    private ExportFixtures() {
    }

    static String hex64(char digit) {
        return String.valueOf(digit).repeat(64);
    }

    static Observation observation(String source, int page, int ordinal, char document, char raw, char version) {
        return new Observation("round-1", source, page, ordinal, "doc-" + hex64(document), hex64(raw), hex64(version));
    }

    static ObjectNode export(Observation observation, String text, String sourceHash) {
        ObjectNode root = JSON.createObjectNode();
        root.put("schemaVersion", IngestionExportParser.SCHEMA_VERSION);
        ObjectNode node = root.putObject("observation");
        node.put("roundId", observation.roundId());
        node.put("sourceId", observation.sourceId());
        node.put("page", observation.page());
        node.put("ordinal", observation.ordinal());
        node.put("pageId", "page-0");
        node.put("observedAt", OBSERVED_AT);
        node.put("documentId", observation.documentId());
        node.put("rawVersion", observation.rawVersion());
        node.put("documentVersion", observation.documentVersion());
        node.put("url", "https://example.invalid/a");
        node.put("title", "authored");
        node.put("publishedAt", PUBLISHED_AT);
        node.putNull("modifiedAt");
        node.putNull("sourceRevision");
        node.put("mediaType", "text/html");
        ObjectNode grant = root.putObject("grant");
        grant.put("grantId", "operator-grant");
        grant.put("revision", "rights-1");
        ObjectNode document = root.putObject("document");
        document.put("documentId", observation.documentId());
        document.put("documentVersion", observation.documentVersion());
        document.put("sourceId", observation.sourceId());
        document.put("textArtifactId", "text-" + observation.documentVersion());
        document.put("inputKind", "body");
        document.put("cleanerVersion", "exact-copy-1");
        document.put("text", text);
        document.put("sourceHash", sourceHash);
        ArrayNode locators = document.putArray("rawLocators");
        ObjectNode locator = locators.addObject();
        locator.put("locatorId", "loc-1");
        locator.put("start", 0);
        locator.put("end", text.length());
        ObjectNode metadata = root.putObject("locatorMetadata");
        metadata.put("rawHash", hex64('9'));
        return root;
    }

    static byte[] bytes(JsonNode node) {
        return JSON.writeValueAsBytes(node);
    }

    static ObjectNode observationOf(ObjectNode export) {
        return (ObjectNode) export.get("observation");
    }

    static ObjectNode documentOf(ObjectNode export) {
        return (ObjectNode) export.get("document");
    }
}
