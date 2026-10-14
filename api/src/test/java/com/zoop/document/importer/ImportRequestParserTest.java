package com.zoop.document.importer;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;

import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import com.zoop.document.service.ArticleKind;
import com.zoop.document.service.PointerPolicy;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ImportRequestParserTest {
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String DOC = "doc-" + "a".repeat(64);
    private static final String RAW = "b".repeat(64);
    private static final String VERSION = "c".repeat(64);

    private final ImportRequestParser parser = new ImportRequestParser();

    private static ObjectNode item() {
        ObjectNode item = JSON.createObjectNode();
        item.put("kind", "news");
        ObjectNode observation = item.putObject("observation");
        observation.put("roundId", "r1");
        observation.put("sourceId", "synthetic-source");
        observation.put("page", 0);
        observation.put("ordinal", 0);
        observation.put("documentId", DOC);
        observation.put("rawVersion", RAW);
        observation.put("documentVersion", VERSION);
        return item;
    }

    private static ObjectNode request(ObjectNode... items) {
        ObjectNode root = JSON.createObjectNode();
        root.put("schemaVersion", ImportRequestParser.SCHEMA_VERSION);
        ArrayNode array = root.putArray("items");
        for (ObjectNode item : items) {
            array.add(item);
        }
        return root;
    }

    private static byte[] bytes(ObjectNode node) {
        return JSON.writeValueAsBytes(node);
    }

    private DocumentImportFailure rejected(byte[] request) {
        DocumentImportException error = assertThrows(DocumentImportException.class, () -> parser.parse(request));
        assertEquals("request_invalid", error.getMessage());
        return error.failure();
    }

    private void assertRejectedItem(Consumer<ObjectNode> mutation) {
        ObjectNode item = item();
        mutation.accept(item);
        assertEquals(DocumentImportFailure.REQUEST_INVALID, rejected(bytes(request(item))));
    }

    @Test
    void parsesTheSelectorVerbatimAndDefaultsToInsertionOnly() {
        ImportRequest parsed = parser.parse(bytes(request(item())));

        assertEquals(1, parsed.items().size());
        ImportItem item = parsed.items().getFirst();
        assertEquals(ArticleKind.NEWS, item.kind());
        assertEquals(new Observation("r1", "synthetic-source", 0, 0, DOC, RAW, VERSION), item.observation());
        assertFalse(item.pointer().move());
    }

    @Test
    void currentVersionDistinguishesAbsentNullAndExactExpectation() {
        ObjectNode expectNull = item();
        expectNull.putObject("currentVersion").putNull("expected");
        ObjectNode expectVersion = item();
        expectVersion.putObject("currentVersion").put("expected", "d".repeat(64));

        List<ImportItem> items = parser.parse(bytes(request(item(), expectNull, expectVersion))).items();

        assertEquals(PointerPolicy.keep(), items.get(0).pointer());
        assertEquals(PointerPolicy.moveFrom(null), items.get(1).pointer());
        assertEquals(PointerPolicy.moveFrom("d".repeat(64)), items.get(2).pointer());
        assertTrue(items.get(1).pointer().move());
    }

    @Test
    void currentVersionMustBeAnObjectWithExactlyExpected() {
        assertRejectedItem(item -> item.putNull("currentVersion"));
        assertRejectedItem(item -> item.putObject("currentVersion"));
        assertRejectedItem(item -> item.putObject("currentVersion").put("expected", "short"));
        assertRejectedItem(item -> item.putObject("currentVersion").put("expected", "D".repeat(64)));
        assertRejectedItem(item -> item.putObject("currentVersion").put("expected", 1));
        assertRejectedItem(item -> item.putObject("currentVersion").putNull("expected").put("force", true));
        assertRejectedItem(item -> item.put("currentVersion", "latest"));
    }

    @Test
    void thereIsNoKeyThroughWhichAnExportTextGrantOrPathCouldBeSupplied() {
        for (String key : List.of("export", "document", "text", "grant", "path", "currentVersionOverride", "access")) {
            assertRejectedItem(item -> item.putObject(key));
        }
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("schemaVersion", "zoop-ingestion-s2-1"));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("url", "https://example.invalid/"));
        assertRejectedItem(item -> item.remove("kind"));
        assertRejectedItem(item -> item.remove("observation"));
        ObjectNode withExtraRoot = request(item());
        withExtraRoot.put("dryRun", true);
        assertEquals(DocumentImportFailure.REQUEST_INVALID, rejected(bytes(withExtraRoot)));
        ObjectNode otherSchema = request(item());
        otherSchema.put("schemaVersion", "zoop-document-import-2");
        assertEquals(DocumentImportFailure.REQUEST_INVALID, rejected(bytes(otherSchema)));
    }

    @Test
    void identifiersMustMatchTheS2ShapesExactly() {
        assertRejectedItem(item -> item.put("kind", "NEWS"));
        assertRejectedItem(item -> item.put("kind", "report"));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("documentId", "a".repeat(64)));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("documentId", "doc-" + "A".repeat(64)));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("documentId", "doc-" + "a".repeat(63)));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("rawVersion", "b".repeat(65)));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("documentVersion", " " + "c".repeat(63)));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("page", -1));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("ordinal", 1.5));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("ordinal", "0"));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("page", 3_000_000_000L));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("roundId", ""));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("sourceId", ""));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("roundId", "r".repeat(201)));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).put("sourceId", "a\u0000b"));
        assertRejectedItem(item -> ((ObjectNode) item.get("observation")).putNull("sourceId"));
    }

    @Test
    void unicodeIdentifiersAreKeptExactlyAndLengthIsCountedInCodePoints() {
        String source = "출처-\uD83D\uDE00-" + "\uac00";
        ObjectNode item = item();
        ((ObjectNode) item.get("observation")).put("sourceId", source);
        ((ObjectNode) item.get("observation")).put("roundId", "\uD83D\uDE00".repeat(200));

        Observation observation = parser.parse(bytes(request(item))).items().getFirst().observation();

        assertEquals(source, observation.sourceId());
        assertEquals("\uD83D\uDE00".repeat(200), observation.roundId());
        // 201 code points are refused even though 200 emoji already use 400 UTF-16 units.
        assertRejectedItem(i -> ((ObjectNode) i.get("observation")).put("roundId", "\uD83D\uDE00".repeat(201)));
    }

    @Test
    void anUnpairedSurrogateIsRefusedNotSilentlyReplaced() {
        String json = new String(bytes(request(item())), StandardCharsets.UTF_8).replace("synthetic-source",
                "bad\\ud800source");
        assertEquals(DocumentImportFailure.REQUEST_INVALID, rejected(json.getBytes(StandardCharsets.UTF_8)));
    }

    @Test
    void oneToOneHundredItemsAreAccepted() {
        List<ObjectNode> hundred = new ArrayList<>();
        for (int i = 0; i < 100; i++) {
            hundred.add(item());
        }
        assertEquals(100, parser.parse(bytes(request(hundred.toArray(new ObjectNode[0])))).items().size());

        hundred.add(item());
        assertEquals(DocumentImportFailure.REQUEST_INVALID,
                rejected(bytes(request(hundred.toArray(new ObjectNode[0])))));
        assertEquals(DocumentImportFailure.REQUEST_INVALID, rejected(bytes(request())));
    }

    @Test
    void malformedAndOversizedFilesAreRefused() {
        byte[] valid = bytes(request(item()));
        assertEquals(DocumentImportFailure.REQUEST_INVALID, rejected(new byte[0]));
        assertEquals(DocumentImportFailure.REQUEST_INVALID, rejected("null".getBytes(StandardCharsets.UTF_8)));
        assertEquals(DocumentImportFailure.REQUEST_INVALID, rejected("[]".getBytes(StandardCharsets.UTF_8)));
        assertEquals(DocumentImportFailure.REQUEST_INVALID,
                rejected((new String(valid, StandardCharsets.UTF_8) + " garbage").getBytes(StandardCharsets.UTF_8)));
        assertEquals(DocumentImportFailure.REQUEST_INVALID,
                rejected(new String(valid, StandardCharsets.UTF_8).replace("\"kind\":\"news\"",
                        "\"kind\":\"news\",\"kind\":\"news\"").getBytes(StandardCharsets.UTF_8)));
        assertEquals(DocumentImportFailure.REQUEST_INVALID,
                rejected(new String(valid, StandardCharsets.UTF_8).replace("\"page\":0", "\"page\":0,\"page\":1")
                        .getBytes(StandardCharsets.UTF_8)));
        byte[] invalidUtf8 = new byte[valid.length + 1];
        System.arraycopy(valid, 0, invalidUtf8, 0, valid.length);
        invalidUtf8[valid.length] = (byte) 0xc3;
        assertEquals(DocumentImportFailure.REQUEST_INVALID, rejected(invalidUtf8));
        ObjectNode padded = request(item());
        padded.put("padding", "x".repeat(ImportRequestParser.MAX_BYTES));
        assertEquals(DocumentImportFailure.REQUEST_INVALID, rejected(bytes(padded)));
    }
}
