package com.zoop.document.bindings;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileSystems;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Stream;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.bindings.DocumentBindingsExporterTest.FakeRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static com.zoop.document.bindings.DocumentBindingsExporterTest.DOC_A;
import static com.zoop.document.bindings.DocumentBindingsExporterTest.DOC_B;
import static com.zoop.document.bindings.DocumentBindingsExporterTest.V1;
import static com.zoop.document.bindings.DocumentBindingsExporterTest.V2;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * The operator entry point: exclusive result and output files, redacted output, non-zero exit (an exception) on any failure.
 * The runner creates owner-only files with POSIX permissions, so these cases run on a POSIX file system (Linux, the CI and
 * container environment) and are reported as skipped, not failed, elsewhere.
 */
class DocumentBindingsRunnerTest {
    @TempDir
    Path temp;
    private Path base;
    private Path output;
    private Path result;
    private Path selection;
    private FakeRepository repository;

    @BeforeEach
    void setUp() throws IOException {
        assumeTrue(FileSystems.getDefault().supportedFileAttributeViews().contains("posix"),
                "the runner creates owner-only files with POSIX permissions");
        base = temp.toRealPath();
        output = base.resolve("bindings.json");
        result = base.resolve("result.json");
        selection = base.resolve("selection.json");
        repository = new FakeRepository().row(DOC_A, V1, "available").row(DOC_A, V2, "private").row(DOC_B, V1, "available");
    }

    private DocumentBindingsRunner runner(DocumentBindingsScope scope, boolean selected) {
        DocumentBindingsSettings settings = new DocumentBindingsSettings(output, result, selected ? selection : null, scope);
        return new DocumentBindingsRunner(settings, new BindingSelectionParser(), new DocumentBindingsExporter(repository));
    }

    /** The default run with the file writer replaced: the first write is the output, the second the result. */
    private DocumentBindingsRunner runner(DocumentBindingsRunner.Writer writer) {
        DocumentBindingsSettings settings = new DocumentBindingsSettings(output, result, null, DocumentBindingsScope.AVAILABLE);
        return new DocumentBindingsRunner(settings, new BindingSelectionParser(), new DocumentBindingsExporter(repository), writer);
    }

    private List<String> files() throws IOException {
        try (Stream<Path> entries = Files.list(base)) {
            return entries.map(path -> path.getFileName().toString()).sorted().toList();
        }
    }

    private Obj result() throws IOException {
        return StrictJson.parseObject(Files.readAllBytes(result));
    }

    private static void assertOwnerOnly(Path path) throws IOException {
        Set<PosixFilePermission> permissions = Files.getPosixFilePermissions(path);
        assertFalse(permissions.stream().anyMatch(p -> p.name().startsWith("GROUP") || p.name().startsWith("OTHERS")));
    }

    @Test
    void aSuccessfulRunWritesTheBindingsAndTheResultExclusivelyAndReturns() throws Exception {
        runner(DocumentBindingsScope.AVAILABLE, false).run(null);

        byte[] bindings = Files.readAllBytes(output);
        Obj written = StrictJson.parseObject(bindings).exactly(Set.of("schemaVersion", "bindings"));
        assertEquals(2, written.objects("bindings").size());
        assertEquals(DOC_A, written.objects("bindings").get(0).string("documentId"));
        assertEquals(DOC_B, written.objects("bindings").get(1).string("documentId"));
        Obj summary = result();
        assertEquals("succeeded", summary.string("status"));
        assertEquals("available", summary.string("scope"));
        assertFalse(summary.bool("selection"));
        assertEquals(2, summary.count("count"));
        assertEquals(bindings.length, summary.count("bytes"));
        assertEquals(Canonical.sha256(bindings), summary.string("sha256"));
        assertEquals(1, summary.object("excluded").count("private"));
        assertFalse(summary.has("failure"));
        assertOwnerOnly(output);
        assertOwnerOnly(result);
    }

    @Test
    void aSelectionFileNarrowsTheRunAndTheResultSaysSo() throws Exception {
        Files.writeString(selection, "{\"schemaVersion\":\"zoop-document-bindings-selection-1\",\"versions\":[{\"documentId\":\""
                + DOC_B + "\",\"documentVersion\":\"" + V1 + "\"}]}");

        runner(DocumentBindingsScope.AVAILABLE, true).run(null);

        Obj written = StrictJson.parseObject(Files.readAllBytes(output));
        assertEquals(1, written.objects("bindings").size());
        assertEquals(DOC_B, written.objects("bindings").get(0).string("documentId"));
        assertTrue(result().bool("selection"));
        assertEquals(1, result().count("count"));
    }

    @Test
    void aFailedExportWritesTheResultLeavesNoOutputAndEndsTheRunWithACodeOnlyException() throws Exception {
        Files.writeString(selection, "{\"schemaVersion\":\"zoop-document-bindings-selection-1\",\"versions\":[{\"documentId\":\""
                + DOC_B + "\",\"documentVersion\":\"" + V2 + "\"}]}");

        DocumentBindingsAbortedException aborted = assertThrows(DocumentBindingsAbortedException.class,
                () -> runner(DocumentBindingsScope.ALL, true).run(null));

        assertEquals(DocumentBindingsFailure.SELECTION_UNREGISTERED, aborted.failure());
        assertEquals("document bindings export failed: selection_unregistered", aborted.getMessage());
        assertFalse(aborted.getMessage().contains(base.toString()));
        assertFalse(Files.exists(output));
        Obj summary = result();
        assertEquals("failed", summary.string("status"));
        assertEquals("selection_unregistered", summary.object("failure").string("code"));
        assertEquals("all", summary.string("scope"));
        assertTrue(summary.bool("selection"));
        assertFalse(summary.has("count"));
    }

    @Test
    void anInvalidOrMissingSelectionFileIsReportedWithoutReadingTheRegistry() throws Exception {
        DocumentBindingsAbortedException missing = assertThrows(DocumentBindingsAbortedException.class,
                () -> runner(DocumentBindingsScope.AVAILABLE, true).run(null));
        assertEquals(DocumentBindingsFailure.SELECTION_INVALID, missing.failure());
        assertEquals("selection_invalid", result().object("failure").string("code"));
        Files.delete(result);

        Files.writeString(selection, "{\"schemaVersion\":\"zoop-document-bindings-selection-1\",\"versions\":[]}");
        DocumentBindingsAbortedException empty = assertThrows(DocumentBindingsAbortedException.class,
                () -> runner(DocumentBindingsScope.AVAILABLE, true).run(null));
        assertEquals(DocumentBindingsFailure.SELECTION_INVALID, empty.failure());
        assertFalse(Files.exists(output));
    }

    @Test
    void anExistingResultFileIsNeverOverwrittenAndNoOutputIsWritten() throws Exception {
        Files.writeString(result, "earlier outcome");

        DocumentBindingsAbortedException aborted = assertThrows(DocumentBindingsAbortedException.class,
                () -> runner(DocumentBindingsScope.AVAILABLE, false).run(null));

        assertEquals(DocumentBindingsFailure.RESULT_UNAVAILABLE, aborted.failure());
        assertEquals("earlier outcome", Files.readString(result));
        assertFalse(Files.exists(output));
    }

    @Test
    void anExistingOutputFileIsNeverOverwrittenAndTheResultSaysWhy() throws Exception {
        Files.writeString(output, "earlier bindings");

        DocumentBindingsAbortedException aborted = assertThrows(DocumentBindingsAbortedException.class,
                () -> runner(DocumentBindingsScope.AVAILABLE, false).run(null));

        assertEquals(DocumentBindingsFailure.OUTPUT_UNAVAILABLE, aborted.failure());
        assertEquals("earlier bindings", Files.readString(output));
        assertEquals("output_unavailable", result().object("failure").string("code"));
    }

    @Test
    void aSecondRunWithTheSamePathsIsRefusedAndTheFirstFilesSurvive() throws Exception {
        runner(DocumentBindingsScope.AVAILABLE, false).run(null);
        String firstOutput = Files.readString(output, StandardCharsets.UTF_8);
        String firstResult = Files.readString(result, StandardCharsets.UTF_8);
        repository.row(DOC_B, V2, "available");

        DocumentBindingsAbortedException aborted = assertThrows(DocumentBindingsAbortedException.class,
                () -> runner(DocumentBindingsScope.AVAILABLE, false).run(null));

        assertEquals(DocumentBindingsFailure.RESULT_UNAVAILABLE, aborted.failure());
        assertEquals(firstOutput, Files.readString(output, StandardCharsets.UTF_8));
        assertEquals(firstResult, Files.readString(result, StandardCharsets.UTF_8));
    }

    @Test
    void theOutputIsNeverVisibleBeforeItIsWholeAndAnInterruptedWriteLeavesNothingBehind() throws Exception {
        AtomicInteger writes = new AtomicInteger();
        List<Boolean> outputSeenMidWrite = new java.util.ArrayList<>();
        DocumentBindingsRunner.Writer interrupted = (channel, content) -> {
            if (writes.incrementAndGet() > 1) {
                DocumentBindingsRunner.WHOLE.write(channel, content);
                return;
            }
            channel.write(ByteBuffer.wrap(content, 0, content.length / 2));
            outputSeenMidWrite.add(Files.exists(output));
            throw new IOException("no space left on device");
        };

        DocumentBindingsAbortedException aborted = assertThrows(DocumentBindingsAbortedException.class,
                () -> runner(interrupted).run(null));

        assertEquals(DocumentBindingsFailure.OUTPUT_UNAVAILABLE, aborted.failure());
        assertEquals(List.of(false), outputSeenMidWrite, "half-written bytes are in a temporary file, not under the output's name");
        assertFalse(Files.exists(output));
        assertEquals(List.of("result.json"), files(), "the temporary file is removed");
        assertEquals("output_unavailable", result().object("failure").string("code"));
    }

    @Test
    void aResultThatCannotBeRecordedRemovesTheOutputThisRunPublished() throws Exception {
        AtomicInteger writes = new AtomicInteger();
        List<Boolean> outputPublishedBeforeResult = new java.util.ArrayList<>();
        DocumentBindingsRunner.Writer resultFails = (channel, content) -> {
            if (writes.incrementAndGet() == 1) {
                DocumentBindingsRunner.WHOLE.write(channel, content);
                return;
            }
            outputPublishedBeforeResult.add(Files.exists(output));
            throw new IOException("I/O error");
        };

        DocumentBindingsAbortedException aborted = assertThrows(DocumentBindingsAbortedException.class,
                () -> runner(resultFails).run(null));

        assertEquals(DocumentBindingsFailure.RESULT_UNAVAILABLE, aborted.failure());
        assertEquals(List.of(true), outputPublishedBeforeResult);
        assertFalse(Files.exists(output), "a non-zero exit never leaves an output behind");
        assertEquals(List.of("result.json"), files());
        assertEquals(0, Files.size(result), "an empty result: outcome unknown, re-run with new paths");
    }

    @Test
    void anUnexpectedFailureIsAnInternalErrorWithoutItsMessage() throws Exception {
        repository.failure = new IllegalStateException("jdbc:postgresql://secret");

        DocumentBindingsAbortedException aborted = assertThrows(DocumentBindingsAbortedException.class,
                () -> runner(DocumentBindingsScope.AVAILABLE, false).run(null));

        assertEquals(DocumentBindingsFailure.INTERNAL_ERROR, aborted.failure());
        assertFalse(Files.readString(result).contains("secret"));
        assertFalse(Files.exists(output));
    }
}
