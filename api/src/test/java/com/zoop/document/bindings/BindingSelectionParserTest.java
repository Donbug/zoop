package com.zoop.document.bindings;

import java.nio.charset.StandardCharsets;
import java.util.List;

import com.zoop.document.bindings.BindingSelection.VersionKey;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class BindingSelectionParserTest {
    private static final String DOC = "doc-" + "a".repeat(64);
    private static final String VERSION = "1".repeat(64);
    private final BindingSelectionParser parser = new BindingSelectionParser();

    private static byte[] bytes(String text) {
        return text.getBytes(StandardCharsets.UTF_8);
    }

    private static String file(String versions) {
        return "{\"schemaVersion\":\"zoop-document-bindings-selection-1\",\"versions\":[" + versions + "]}";
    }

    private static String entry(String document, String version) {
        return "{\"documentId\":\"" + document + "\",\"documentVersion\":\"" + version + "\"}";
    }

    private void assertInvalid(String text) {
        DocumentBindingsException refused = assertThrows(DocumentBindingsException.class, () -> parser.parse(bytes(text)), text);
        assertEquals(DocumentBindingsFailure.SELECTION_INVALID, refused.failure(), text);
    }

    @Test
    void readsTheVersionsInFileOrder() {
        String other = "doc-" + "b".repeat(64);

        BindingSelection selection = parser.parse(bytes(file(entry(other, VERSION) + "," + entry(DOC, VERSION))));

        assertEquals(List.of(new VersionKey(other, VERSION), new VersionKey(DOC, VERSION)), selection.versions());
    }

    @Test
    void theSchemaTheKeysAndTheShapesAreExact() {
        assertInvalid("{\"schemaVersion\":\"zoop-document-bindings-selection-2\",\"versions\":[" + entry(DOC, VERSION) + "]}");
        assertInvalid("{\"versions\":[" + entry(DOC, VERSION) + "]}");
        assertInvalid(file(entry(DOC, VERSION)).replace("}]}", "}],\"scope\":\"all\"}"));
        assertInvalid(file("{\"documentId\":\"" + DOC + "\"}"));
        assertInvalid(file(entry(DOC, VERSION).replace("}", ",\"articleId\":\"" + DOC + "\"}")));
        assertInvalid(file(entry("art-" + "a".repeat(64), VERSION)));
        assertInvalid(file(entry(DOC, "1".repeat(63))));
        assertInvalid(file(entry(DOC, "A".repeat(64))));
        assertInvalid(file("\"" + DOC + "\""));
        assertInvalid("[]");
        assertInvalid("not json");
    }

    @Test
    void theListHasOneToTheContractLimitEntriesAndNoVersionTwice() {
        assertInvalid(file(""));
        assertInvalid(file(entry(DOC, VERSION) + "," + entry(DOC, VERSION)));

        StringBuilder many = new StringBuilder();
        for (int index = 0; index <= DocumentBindingsExporter.MAX_BINDINGS; index++) {
            if (index > 0) {
                many.append(',');
            }
            many.append(entry(DOC, String.format("%064x", index)));
        }
        assertInvalid(file(many.toString()));
    }

    @Test
    void aFileThatIsNotStrictUtf8IsInvalid() {
        byte[] broken = file(entry(DOC, VERSION)).getBytes(StandardCharsets.UTF_8);
        broken[broken.length - 1] = (byte) 0xff;

        DocumentBindingsException refused = assertThrows(DocumentBindingsException.class, () -> parser.parse(broken));

        assertEquals(DocumentBindingsFailure.SELECTION_INVALID, refused.failure());
    }
}
