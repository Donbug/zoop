package com.zoop.document.analysis;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;

/**
 * The operator entry point: runs once at startup, only when {@code zoop.document-analysis.enabled=true}, in a non-web
 * application. It reserves the result file exclusively (an existing file is never overwritten), reads and validates the
 * request, runs the batch, writes the redacted result and, when anything failed, ends the run with an exception so the process
 * exits non-zero. The result file is reserved before any work: if the process dies mid-run it stays empty, which means
 * "outcome unknown, re-run with a new result path" (every step is idempotent and a pending analysis is simply advanced again).
 */
public final class DocumentAnalysisRunner implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(DocumentAnalysisRunner.class);

    private final DocumentAnalysisSettings settings;
    private final AnalysisRequestParser requestParser;
    private final DocumentAnalyzer analyzer;

    public DocumentAnalysisRunner(DocumentAnalysisSettings settings, AnalysisRequestParser requestParser, DocumentAnalyzer analyzer) {
        this.settings = settings;
        this.requestParser = requestParser;
        this.analyzer = analyzer;
    }

    @Override
    public void run(ApplicationArguments arguments) {
        FileChannel resultFile = reserveResult();
        AnalysisRunResult result;
        try {
            result = execute();
        } catch (RuntimeException unexpected) {
            log.error("document analysis failed unexpectedly: {}", unexpected.getClass().getName());
            result = AnalysisRunResult.requestFailed(null, AnalysisFailure.INTERNAL_ERROR, Map.of(), List.of());
        }
        try (resultFile) {
            ByteBuffer buffer = ByteBuffer.wrap(AnalysisResultWriter.toBytes(result));
            while (buffer.hasRemaining()) {
                resultFile.write(buffer);
            }
            resultFile.force(true);
        } catch (IOException error) {
            log.error("document analysis result file could not be written: {}", error.getClass().getSimpleName());
            throw new DocumentAnalysisAbortedException(AnalysisFailure.RESULT_UNAVAILABLE);
        }
        if (!result.succeeded()) {
            throw new DocumentAnalysisAbortedException(result.firstFailure());
        }
        log.info("document analysis {} succeeded: {} item(s)", result.command(), result.items().size());
    }

    private AnalysisRunResult execute() {
        AnalysisRequest request;
        try {
            request = requestParser.parse(readRequest());
        } catch (AnalysisException invalid) {
            log.warn("document analysis request rejected: {}", invalid.failure().code());
            return AnalysisRunResult.requestFailed(null, invalid.failure(), invalid.details(), List.of());
        }
        return analyzer.run(request);
    }

    private byte[] readRequest() {
        try (InputStream in = Files.newInputStream(settings.request())) {
            byte[] bytes = in.readNBytes(AnalysisRequestParser.MAX_BYTES + 1);
            if (bytes.length > AnalysisRequestParser.MAX_BYTES) {
                throw new AnalysisException(AnalysisFailure.REQUEST_INVALID);
            }
            return bytes;
        } catch (IOException error) {
            throw new AnalysisException(AnalysisFailure.REQUEST_INVALID);
        }
    }

    private FileChannel reserveResult() {
        try {
            return FileChannel.open(settings.result(), Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                    LinkOption.NOFOLLOW_LINKS), PosixFilePermissions.asFileAttribute(
                            PosixFilePermissions.fromString("rw-------")));
        } catch (IOException | RuntimeException error) {
            log.error("document analysis result file could not be created: {}", error.getClass().getSimpleName());
            throw new DocumentAnalysisAbortedException(AnalysisFailure.RESULT_UNAVAILABLE);
        }
    }
}
