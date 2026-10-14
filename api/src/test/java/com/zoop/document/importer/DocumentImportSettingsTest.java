package com.zoop.document.importer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.function.Supplier;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DocumentImportSettingsTest {
    @TempDir
    Path temp;
    private Path base;
    private Path request;
    private Path result;
    private Path cli;
    private Path state;
    private Path sources;
    private Path artifacts;

    @BeforeEach
    void setUp() throws IOException {
        base = temp.toRealPath();
        request = Files.writeString(base.resolve("request.json"), "{}");
        result = base.resolve("out").resolve("result.json");
        Files.createDirectory(base.resolve("out"));
        cli = Files.writeString(base.resolve("zoop-ai-ingest"), "#!/bin/sh\n");
        Files.setPosixFilePermissions(cli, PosixFilePermissions.fromString("rwx------"));
        state = Files.createDirectory(base.resolve("ingestion-state"));
        sources = Files.writeString(base.resolve("sources.json"), "{}");
        artifacts = Files.createDirectory(base.resolve("artifacts"));
    }

    private DocumentImportSettings settings() {
        return DocumentImportSettings.of(request.toString(), result.toString(), cli.toString(), state.toString(),
                sources.toString(), artifacts.toString());
    }

    private DocumentImportSettings settings(String requestValue, String resultValue, String cliValue, String stateValue,
            String sourcesValue, String artifactsValue) {
        return DocumentImportSettings.of(requestValue, resultValue, cliValue, stateValue, sourcesValue, artifactsValue);
    }

    private void assertNames(String setting, Supplier<DocumentImportSettings> action) {
        DocumentImportConfigurationException error = assertThrows(DocumentImportConfigurationException.class, action::get);
        assertTrue(error.getMessage().startsWith("zoop.document-import." + setting + " "), error.getMessage());
        // The message names the setting and a rule, never a configured value.
        assertFalse(error.getMessage().contains(base.toString()), error.getMessage());
    }

    @Test
    void validPathsAreAccepted() {
        DocumentImportSettings settings = settings();

        assertEquals(request, settings.request());
        assertEquals(result, settings.result());
        assertEquals(cli, settings.ingestionCli());
        assertEquals(state, settings.ingestionState());
        assertEquals(sources, settings.ingestionSources());
        assertEquals(artifacts, settings.artifactRoot());
    }

    @Test
    void everyPathMustBeSetAbsoluteAndNormalised() {
        String[] valid = {request.toString(), result.toString(), cli.toString(), state.toString(), sources.toString(),
                artifacts.toString()};
        String[] names = {"request", "result", "ingestion-cli", "ingestion-state-dir", "ingestion-sources", "artifact-root"};
        for (int index = 0; index < valid.length; index++) {
            for (String bad : new String[] {null, "", "   ", "relative/path", "./x", base + "/../x", base + "/./x"}) {
                String[] values = valid.clone();
                values[index] = bad;
                assertNames(names[index], () -> settings(values[0], values[1], values[2], values[3], values[4], values[5]));
            }
        }
    }

    @Test
    void theRequestCliAndSourcesMustBeFilesAndTheCliExecutable() throws IOException {
        request = base.resolve("missing.json");
        assertNames("request", this::settings);
        request = Files.createDirectory(base.resolve("a-directory"));
        assertNames("request", this::settings);
        request = Files.writeString(base.resolve("request-ok.json"), "{}");

        Files.setPosixFilePermissions(cli, PosixFilePermissions.fromString("rw-------"));
        assertNames("ingestion-cli", this::settings);
        Files.setPosixFilePermissions(cli, PosixFilePermissions.fromString("rwx------"));
        cli = base.resolve("missing-cli");
        assertNames("ingestion-cli", this::settings);
        cli = state;
        assertNames("ingestion-cli", this::settings);
        cli = Files.writeString(base.resolve("cli-ok"), "#!/bin/sh\n");
        Files.setPosixFilePermissions(cli, PosixFilePermissions.fromString("rwx------"));

        sources = base.resolve("missing-sources.json");
        assertNames("ingestion-sources", this::settings);
    }

    @Test
    void theStateDirectoryAndArtifactRootMustBeExistingDirectories() throws IOException {
        state = base.resolve("missing-state");
        assertNames("ingestion-state-dir", this::settings);
        state = Files.writeString(base.resolve("state-file"), "x");
        assertNames("ingestion-state-dir", this::settings);
        state = Files.createDirectory(base.resolve("state-ok"));

        artifacts = base.resolve("missing-artifacts");
        assertNames("artifact-root", this::settings);
        artifacts = Files.writeString(base.resolve("artifacts-file"), "x");
        assertNames("artifact-root", this::settings);
    }

    @Test
    void theArtifactRootHasNoSymlinkComponent() throws IOException {
        Path link = Files.createSymbolicLink(base.resolve("artifacts-link"), artifacts);
        artifacts = link;
        assertNames("artifact-root", this::settings);

        Path nested = Files.createDirectory(artifacts.toRealPath().resolve("nested"));
        Path parentLink = Files.createSymbolicLink(base.resolve("parent-link"), nested.getParent());
        artifacts = parentLink.resolve("nested");
        assertNames("artifact-root", this::settings);
    }

    @Test
    void theArtifactRootAndTheIngestionStateNeverOverlap() throws IOException {
        artifacts = state;
        assertNames("artifact-root", this::settings);
        artifacts = Files.createDirectory(state.resolve("artifacts"));
        assertNames("artifact-root", this::settings);
        artifacts = base;
        assertNames("artifact-root", this::settings);
    }

    @Test
    void theCliRejectsStrayFilesInItsStateDirectoryAndSoNoInputOrOutputMayLiveThere() throws IOException {
        request = Files.writeString(state.resolve("request.json"), "{}");
        assertNames("request", this::settings);
        request = Files.writeString(base.resolve("request-ok.json"), "{}");

        result = state.resolve("result.json");
        assertNames("result", this::settings);
    }

    @Test
    void theResultMustNotExistAndItsParentMust() throws IOException {
        Files.writeString(result, "earlier result");
        assertNames("result", this::settings);
        Files.delete(result);
        Files.createSymbolicLink(result, base.resolve("nowhere"));
        assertNames("result", this::settings);
        Files.delete(result);

        result = base.resolve("no-such-dir").resolve("result.json");
        assertNames("result", this::settings);
    }
}
