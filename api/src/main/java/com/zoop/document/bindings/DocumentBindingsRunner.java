package com.zoop.document.bindings;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.FileAttribute;
import java.nio.file.attribute.PosixFilePermission;
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
 * builds the bindings, publishes the output, writes the result and, when anything failed, ends the run with an exception so
 * the process exits non-zero.
 *
 * <p>The output is never visible before it is whole: the bytes go to an owner-only temporary file next to it, are forced to
 * disk, and the file is then given the output's name in one rename that never replaces an existing file. A write that fails
 * removes the temporary file; a result that cannot be recorded removes the output this run published, so an output file that
 * exists holds the whole export and was reported in a result. A run that died leaves an empty result ("outcome unknown,
 * re-run with new paths"; the export writes nothing to the database, so a re-run is always safe) and possibly a
 * {@code <output>.<random>.tmp} next to the output, which is safe to delete.
 */
public final class DocumentBindingsRunner implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(DocumentBindingsRunner.class);
    private static final FileAttribute<Set<PosixFilePermission>> OWNER_ONLY =
            PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"));

    /** Writes the whole content to an open channel and forces it to disk; replaceable so a test can interrupt a write. */
    interface Writer {
        void write(FileChannel channel, byte[] content) throws IOException;
    }

    static final Writer WHOLE = DocumentBindingsRunner::writeFully;

    private final DocumentBindingsSettings settings;
    private final BindingSelectionParser selectionParser;
    private final DocumentBindingsExporter exporter;
    private final Writer writer;

    public DocumentBindingsRunner(DocumentBindingsSettings settings, BindingSelectionParser selectionParser,
            DocumentBindingsExporter exporter) {
        this(settings, selectionParser, exporter, WHOLE);
    }

    DocumentBindingsRunner(DocumentBindingsSettings settings, BindingSelectionParser selectionParser,
            DocumentBindingsExporter exporter, Writer writer) {
        this.settings = settings;
        this.selectionParser = selectionParser;
        this.exporter = exporter;
        this.writer = writer;
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
            writer.write(resultFile, DocumentBindingsResultWriter.toBytes(result));
        } catch (IOException error) {
            log.error("document bindings result file could not be written: {}", error.getClass().getSimpleName());
            // The run fails, so the output it published must not survive: an output that exists was reported in a result.
            if (result.succeeded()) {
                discard(settings.output(), "output of a run whose result could not be recorded");
            }
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
        // Only a complete export reaches the output's name: written whole to a temporary file beside it, forced, then renamed.
        Path temporary = temporary(settings.output());
        try (FileChannel channel = FileChannel.open(temporary, StandardOpenOption.WRITE)) {
            writer.write(channel, export.bytes());
        } catch (IOException error) {
            log.error("document bindings output could not be written: {}", error.getClass().getSimpleName());
            discard(temporary, "partial output");
            throw new DocumentBindingsException(DocumentBindingsFailure.OUTPUT_UNAVAILABLE);
        }
        publish(temporary, settings.output());
        return DocumentBindingsResult.succeeded(settings.scope(), selected, export);
    }

    /** An owner-only, uniquely named file in the output's directory, so the rename that publishes it stays on one file system. */
    private static Path temporary(Path output) {
        try {
            return Files.createTempFile(output.getParent(), output.getFileName() + ".", ".tmp", OWNER_ONLY);
        } catch (IOException | RuntimeException error) {
            log.error("document bindings temporary output could not be created: {}", error.getClass().getSimpleName());
            throw new DocumentBindingsException(DocumentBindingsFailure.OUTPUT_UNAVAILABLE);
        }
    }

    /**
     * Gives the complete, forced temporary file the output's name in one rename. Without {@code REPLACE_EXISTING} an existing
     * file (or link) of that name is never touched: the move is refused and the temporary file removed.
     */
    private static void publish(Path temporary, Path output) {
        try {
            Files.move(temporary, output);
        } catch (FileAlreadyExistsException exists) {
            log.error("document bindings output already exists ({})", DocumentBindingsFailure.OUTPUT_UNAVAILABLE.code());
            discard(temporary, "complete but unpublished output");
            throw new DocumentBindingsException(DocumentBindingsFailure.OUTPUT_UNAVAILABLE);
        } catch (IOException | RuntimeException error) {
            log.error("document bindings output could not be published: {}", error.getClass().getSimpleName());
            discard(temporary, "complete but unpublished output");
            throw new DocumentBindingsException(DocumentBindingsFailure.OUTPUT_UNAVAILABLE);
        }
    }

    /** Removes a file this run created; nothing it did not create is ever deleted. */
    private static void discard(Path path, String what) {
        try {
            if (Files.deleteIfExists(path)) {
                log.info("document bindings export removed its {}", what);
            }
        } catch (IOException error) {
            log.warn("document bindings {} could not be removed: {}", what, error.getClass().getSimpleName());
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
                    LinkOption.NOFOLLOW_LINKS), OWNER_ONLY);
        } catch (IOException | RuntimeException error) {
            log.error("document bindings file could not be created ({}): {}", failure.code(), error.getClass().getSimpleName());
            throw new DocumentBindingsAbortedException(failure);
        }
    }
}
