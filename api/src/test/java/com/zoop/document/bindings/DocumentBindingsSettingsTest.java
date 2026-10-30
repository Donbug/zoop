package com.zoop.document.bindings;

import java.io.IOException;
import java.nio.file.FileSystems;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.function.Supplier;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class DocumentBindingsSettingsTest {
    @TempDir
    Path temp;
    private Path base;
    private Path output;
    private Path result;
    private Path selection;
    private String scope;

    @BeforeEach
    void setUp() throws IOException {
        base = temp.toRealPath();
        Files.createDirectory(base.resolve("out"));
        output = base.resolve("out").resolve("bindings.json");
        result = base.resolve("out").resolve("result.json");
        selection = Files.writeString(base.resolve("selection.json"), "{}");
        scope = "available";
    }

    private DocumentBindingsSettings settings() {
        return DocumentBindingsSettings.of(output.toString(), result.toString(), selection == null ? null : selection.toString(),
                scope);
    }

    private void assertNames(String setting, Supplier<DocumentBindingsSettings> action) {
        DocumentBindingsConfigurationException error = assertThrows(DocumentBindingsConfigurationException.class, action::get);
        assertTrue(error.getMessage().startsWith("zoop.document-bindings." + setting + " "), error.getMessage());
        // The message names the setting and a rule, never a configured value.
        assertFalse(error.getMessage().contains(base.toString()), error.getMessage());
    }

    /** Symbolic links need a POSIX file system (or a privilege Windows does not grant by default). */
    private static void assumeSymbolicLinks() {
        assumeTrue(FileSystems.getDefault().supportedFileAttributeViews().contains("posix"), "symbolic links are required");
    }

    @Test
    void validSettingsAreAccepted() {
        DocumentBindingsSettings settings = settings();

        assertEquals(output, settings.output());
        assertEquals(result, settings.result());
        assertEquals(selection, settings.selection());
        assertEquals(DocumentBindingsScope.AVAILABLE, settings.scope());
    }

    @Test
    void theSelectionIsOptionalAndTheScopeMayBeAll() {
        selection = null;
        scope = "all";

        DocumentBindingsSettings settings = settings();

        assertNull(settings.selection());
        assertEquals(DocumentBindingsScope.ALL, settings.scope());
        assertNull(DocumentBindingsSettings.of(output.toString(), result.toString(), "   ", "all").selection());
    }

    @Test
    void everyPathMustBeSetAbsoluteAndNormalised() {
        String[] names = {"output", "result", "selection"};
        for (int index = 0; index < names.length; index++) {
            for (String bad : new String[] {"relative/path", "./x", base + "/../x", base + "/./x"}) {
                String[] values = {output.toString(), result.toString(), selection.toString()};
                values[index] = bad;
                assertNames(names[index], () -> DocumentBindingsSettings.of(values[0], values[1], values[2], scope));
            }
        }
        assertNames("output", () -> DocumentBindingsSettings.of(null, result.toString(), null, scope));
        assertNames("output", () -> DocumentBindingsSettings.of("", result.toString(), null, scope));
        assertNames("result", () -> DocumentBindingsSettings.of(output.toString(), " ", null, scope));
    }

    @Test
    void theOutputAndTheResultMustNotExistAndTheirParentsMust() throws IOException {
        Files.writeString(output, "earlier bindings");
        assertNames("output", this::settings);
        Files.delete(output);

        Files.writeString(result, "earlier result");
        assertNames("result", this::settings);
        Files.delete(result);

        output = base.resolve("no-such-dir").resolve("bindings.json");
        assertNames("output", this::settings);
        output = base.resolve("out").resolve("bindings.json");
        result = base.resolve("no-such-dir").resolve("result.json");
        assertNames("result", this::settings);
    }

    @Test
    void aDanglingLinkCountsAsExisting() throws IOException {
        assumeSymbolicLinks();
        Files.createSymbolicLink(output, base.resolve("nowhere"));
        assertNames("output", this::settings);
    }

    @Test
    void theOutputAndTheResultMustDiffer() {
        result = output;
        assertNames("result", this::settings);
    }

    @Test
    void theOutputAndTheResultMustDifferEvenThroughALinkedDirectory() throws IOException {
        assumeSymbolicLinks();
        Path linked = Files.createSymbolicLink(base.resolve("out-link"), base.resolve("out"));
        result = linked.resolve("bindings.json");
        assertNames("result", this::settings);

        result = linked.resolve("result.json");
        assertEquals(result, settings().result());
    }

    @Test
    void theSelectionMustBeAnExistingFile() throws IOException {
        selection = base.resolve("missing.json");
        assertNames("selection", this::settings);
        selection = Files.createDirectory(base.resolve("a-directory"));
        assertNames("selection", this::settings);
    }

    @Test
    void theScopeMustBeAvailableOrAll() {
        for (String bad : new String[] {null, "", "AVAILABLE", "everything", "available "}) {
            scope = bad;
            assertNames("scope", this::settings);
        }
    }
}
