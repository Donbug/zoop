package com.zoop.document.bindings;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Set;

import com.zoop.document.bindings.DocumentBindingsExporter.Export;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;

/**
 * The operator entry point: runs once at startup, only when {@code zoop.document-bindings.enabled=true}, in a non-web
 * application. It reserves the result file exclusively (an existing file is never overwritten), reads the optional selection,
 * builds the bindings, creates the output file exclusively and writes it, writes the result and, when anything failed, ends the
 * run with an exception so the process exits non-zero. The result is reserved before any work and the output only after the
 * bindings are complete; an output this run created but could not write whole is removed again, so an output file that exists
 * holds the whole export. A run that died leaves an empty result ("outcome unknown, re-run with new paths"; the export writes
 * nothing to the database, so a re-run is always safe).
 */
public final class DocumentBindingsRunner implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(DocumentBindingsRunner.class);

    private final DocumentBindingsSettings settings;
    private final BindingSelectionParser selectionParser;
    private final DocumentBindingsExporter exporter;

    public DocumentBindingsRunner(DocumentBindingsSettings settings, BindingSelectionParser selectionParser,
            DocumentBindingsExporter exporter) {
        this.settings = settings;
        this.selectionParser = selectionParser;
        this.exporter = exporter;
    }

    @Override
    public void run(ApplicationArguments arguments) {
        FileChannel resultFile = reserve(settings.result(), DocumentBindingsFailure.RESULT_UNAVAILABLE);
        boolean selected = settings.selection() != null;
        DocumentBindingsResult result;
        try {
            result = execute(selected);
        } catch (DocumentBindingsException failure) {
            log.warn("document bindings export failed: {}", failure.failure().code());
            result = DocumentBindingsResult.failed(settings.scope(), selected, failure.failure());
        } catch (RuntimeException unexpected) {
            log.error("document bindings export failed unexpectedly: {}", unexpected.getClass().getName());
            result = DocumentBindingsResult.failed(settings.scope(), selected, DocumentBindingsFailure.INTERNAL_ERROR);
        }
        try (resultFile) {
            writeFully(resultFile, DocumentBindingsResultWriter.toBytes(result));
        } catch (IOException error) {
            log.error("document bindings result file could not be written: {}", error.getClass().getSimpleName());
            throw new DocumentBindingsAbortedException(DocumentBindingsFailure.RESULT_UNAVAILABLE);
        }
        if (!result.succeeded()) {
            throw new DocumentBindingsAbortedException(result.failure());
        }
        log.info("document bindings export succeeded: {} binding(s), {} byte(s), sha256 {}", result.export().count(),
                result.export().size(), result.export().sha256());
    }

    private DocumentBindingsResult execute(boolean selected) {
        BindingSelection selection = selected ? selectionParser.parse(readSelection()) : null;
        Export export = exporter.export(settings.scope(), selection);
        // Only a complete export reaches the file system: the output is created after the bindings exist and written whole.
        FileChannel outputFile;
        try {
            outputFile = reserve(settings.output(), DocumentBindingsFailure.OUTPUT_UNAVAILABLE);
        } catch (DocumentBindingsAbortedException reservation) {
            throw new DocumentBindingsException(reservation.failure());
        }
        try (outputFile) {
            writeFully(outputFile, export.bytes());
        } catch (IOException error) {
            log.error("document bindings output file could not be written: {}", error.getClass().getSimpleName());
            discard(settings.output());
            throw new DocumentBindingsException(DocumentBindingsFailure.OUTPUT_UNAVAILABLE);
        }
        return DocumentBindingsResult.succeeded(settings.scope(), selected, export);
    }

    /** Removes the output this run created exclusively but could not write whole; a partial bindings file must not survive. */
    private static void discard(Path output) {
        try {
            if (Files.deleteIfExists(output)) {
                log.info("document bindings export removed its partial output");
            }
        } catch (IOException error) {
            log.warn("document bindings partial output could not be removed: {}", error.getClass().getSimpleName());
        }
    }

    private byte[] readSelection() {
        try (InputStream in = Files.newInputStream(settings.selection())) {
            byte[] bytes = in.readNBytes(BindingSelectionParser.MAX_BYTES + 1);
            if (bytes.length > BindingSelectionParser.MAX_BYTES) {
                throw new DocumentBindingsException(DocumentBindingsFailure.SELECTION_INVALID);
            }
            return bytes;
        } catch (IOException error) {
            throw new DocumentBindingsException(DocumentBindingsFailure.SELECTION_INVALID);
        }
    }

    private static void writeFully(FileChannel channel, byte[] content) throws IOException {
        ByteBuffer buffer = ByteBuffer.wrap(content);
        while (buffer.hasRemaining()) {
            channel.write(buffer);
        }
        channel.force(true);
    }

    /** Creates the file exclusively, owner read/write only; an existing file (or link) of that name is never touched. */
    private static FileChannel reserve(Path path, DocumentBindingsFailure failure) {
        try {
            return FileChannel.open(path, Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                    LinkOption.NOFOLLOW_LINKS), PosixFilePermissions.asFileAttribute(
                            PosixFilePermissions.fromString("rw-------")));
        } catch (IOException | RuntimeException error) {
            log.error("document bindings file could not be created ({}): {}", failure.code(), error.getClass().getSimpleName());
            throw new DocumentBindingsAbortedException(failure);
        }
    }
}
