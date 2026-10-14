package com.zoop.document.importer;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.List;
import java.util.Set;

import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;

/**
 * The operator entry point: runs once at startup, only when {@code zoop.document-import.enabled=true}, in a non-web
 * application. It reserves the result file exclusively (an existing file is never overwritten), reads and validates the
 * request, runs the batch, writes the redacted result and, when anything failed, ends the run with an exception so the
 * process exits non-zero. The result file is reserved before any work: if the process dies mid-run it stays empty, which
 * means "outcome unknown, re-run with a new result path" (every step is idempotent).
 */
public final class DocumentImportRunner implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(DocumentImportRunner.class);

    private final DocumentImportSettings settings;
    private final ImportRequestParser requestParser;
    private final DocumentImporter importer;

    public DocumentImportRunner(DocumentImportSettings settings, ImportRequestParser requestParser,
            DocumentImporter importer) {
        this.settings = settings;
        this.requestParser = requestParser;
        this.importer = importer;
    }

    @Override
    public void run(ApplicationArguments arguments) {
        FileChannel resultFile = reserveResult();
        DocumentImportResult result;
        try {
            result = execute();
        } catch (RuntimeException unexpected) {
            log.error("document import failed unexpectedly: {}", unexpected.getClass().getName());
            result = DocumentImportResult.requestFailed(DocumentImportFailure.INTERNAL_ERROR, List.of());
        }
        try (resultFile) {
            ByteBuffer buffer = ByteBuffer.wrap(DocumentImportResultWriter.toBytes(result));
            while (buffer.hasRemaining()) {
                resultFile.write(buffer);
            }
            resultFile.force(true);
        } catch (IOException error) {
            log.error("document import result file could not be written: {}", error.getClass().getSimpleName());
            throw new DocumentImportAbortedException(DocumentImportFailure.RESULT_UNAVAILABLE);
        }
        if (!result.succeeded()) {
            throw new DocumentImportAbortedException(result.firstFailure());
        }
        log.info("document import succeeded: {} item(s)", result.items().size());
    }

    private DocumentImportResult execute() {
        ImportRequest request;
        try {
            request = requestParser.parse(readRequest());
        } catch (DocumentImportException invalid) {
            log.warn("document import request rejected: {}", invalid.failure().code());
            return DocumentImportResult.requestFailed(invalid.failure(), List.of());
        }
        return importer.run(request);
    }

    private byte[] readRequest() {
        try (InputStream in = Files.newInputStream(settings.request())) {
            byte[] bytes = in.readNBytes(ImportRequestParser.MAX_BYTES + 1);
            if (bytes.length > ImportRequestParser.MAX_BYTES) {
                throw new DocumentImportException(DocumentImportFailure.REQUEST_INVALID);
            }
            return bytes;
        } catch (IOException error) {
            throw new DocumentImportException(DocumentImportFailure.REQUEST_INVALID);
        }
    }

    private FileChannel reserveResult() {
        try {
            return FileChannel.open(settings.result(), Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                    LinkOption.NOFOLLOW_LINKS), PosixFilePermissions.asFileAttribute(
                            PosixFilePermissions.fromString("rw-------")));
        } catch (IOException | RuntimeException error) {
            log.error("document import result file could not be created: {}", error.getClass().getSimpleName());
            throw new DocumentImportAbortedException(DocumentImportFailure.RESULT_UNAVAILABLE);
        }
    }
}
