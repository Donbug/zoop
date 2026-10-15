package com.zoop.document.evidence.config;

import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Unset is allowed (the read answers 503 where it needs the value); a set value must be usable, and a failure names only the setting. */
class DocumentReadPropertiesTest {
    @TempDir
    Path temp;

    private static String message(Runnable action) {
        return assertThrows(DocumentReadConfigurationException.class, action::run).getMessage();
    }

    @Test
    void unsetOrBlankValuesAreAllowed() {
        for (String blank : new String[] {null, "", "  "}) {
            DocumentReadProperties properties = new DocumentReadProperties(blank, blank);
            assertNull(properties.grantsPath());
            assertNull(properties.artifactRootPath());
        }
    }

    @Test
    void aSetValueMustBeANormalizedAbsolutePathToAnExistingFileOrDirectory() throws Exception {
        Path file = Files.writeString(temp.resolve("grants.json"), "{}");
        Path directory = Files.createDirectory(temp.resolve("artifacts"));

        DocumentReadProperties valid = new DocumentReadProperties(file.toString(), directory.toString());
        assertEquals(file, valid.grantsPath());
        assertEquals(directory, valid.artifactRootPath());

        assertEquals("zoop.document-read.grants must be a normalized absolute path",
                message(() -> new DocumentReadProperties("grants.json", null).grantsPath()));
        assertEquals("zoop.document-read.grants must be a normalized absolute path",
                message(() -> new DocumentReadProperties(temp + "/../" + temp.getFileName() + "/grants.json", null).grantsPath()));
        assertEquals("zoop.document-read.grants must be an existing file",
                message(() -> new DocumentReadProperties(temp.resolve("missing.json").toString(), null).grantsPath()));
        assertEquals("zoop.document-read.grants must be an existing file",
                message(() -> new DocumentReadProperties(directory.toString(), null).grantsPath()));
        assertEquals("zoop.document-read.artifact-root must be a normalized absolute path",
                message(() -> new DocumentReadProperties(null, "relative/root").artifactRootPath()));
        assertEquals("zoop.document-read.artifact-root must be an existing directory",
                message(() -> new DocumentReadProperties(null, file.toString()).artifactRootPath()));
        assertEquals("zoop.document-read.artifact-root must be an existing directory",
                message(() -> new DocumentReadProperties(null, temp.resolve("missing").toString()).artifactRootPath()));
    }

    @Test
    void theFailureAndToStringNeverCarryThePathValue() {
        String secret = temp.resolve("secret-location.json").toString();
        DocumentReadProperties properties = new DocumentReadProperties(secret, secret);

        assertFalse(message(properties::grantsPath).contains("secret-location"));
        assertFalse(message(properties::artifactRootPath).contains("secret-location"));
        assertFalse(properties.toString().contains("secret-location"));
        assertTrue(properties.toString().contains("grants=set"));
    }
}
