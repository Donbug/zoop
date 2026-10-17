package com.zoop.graph.importer;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Set;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;

/**
 * The operator entry point: runs once at startup, only when {@code zoop.graph-handoff-import.enabled=true}, in a non-web
 * application. It reserves the result file exclusively (an existing file is never overwritten), reads and validates the request,
 * runs the import, writes the redacted result and, when it failed, ends the run with an exception so the process exits non-zero.
 * The result file is reserved before any work: if the process dies mid-run it stays empty, which means "outcome unknown, re-run
 * with a new result path" (every step is idempotent: the same pins stage once and answer {@code unchanged} afterwards).
 */
public final class GraphHandoffRunner implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(GraphHandoffRunner.class);

    private final GraphHandoffImportSettings settings;
    private final GraphHandoffRequestParser requestParser;
    private final GraphHandoffImporter importer;

    public GraphHandoffRunner(GraphHandoffImportSettings settings, GraphHandoffRequestParser requestParser,
            GraphHandoffImporter importer) {
        this.settings = settings;
        this.requestParser = requestParser;
        this.importer = importer;
    }

    @Override
    public void run(ApplicationArguments arguments) {
        FileChannel resultFile = reserveResult();
        GraphHandoffResult result;
        try {
            result = execute();
        } catch (RuntimeException unexpected) {
            log.error("graph handoff import failed unexpectedly: {}", unexpected.getClass().getName());
            result = GraphHandoffResult.failed(new GraphHandoffException(GraphHandoffFailure.INTERNAL_ERROR));
        }
        try (resultFile) {
            ByteBuffer buffer = ByteBuffer.wrap(GraphHandoffResultWriter.toBytes(result));
            while (buffer.hasRemaining()) {
                resultFile.write(buffer);
            }
            resultFile.force(true);
        } catch (IOException error) {
            log.error("graph handoff import result file could not be written: {}", error.getClass().getSimpleName());
            throw new GraphHandoffAbortedException(GraphHandoffFailure.RESULT_UNAVAILABLE);
        }
        if (!result.succeeded()) {
            throw new GraphHandoffAbortedException(result.failure().failure());
        }
        log.info("graph handoff import succeeded: {}", result.staged().outcome().wire());
    }

    private GraphHandoffResult execute() {
        GraphHandoffRequest request;
        try {
            request = requestParser.parse(readRequest());
        } catch (GraphHandoffException invalid) {
            log.warn("graph handoff import request rejected: {}", invalid.failure().code());
            return GraphHandoffResult.failed(invalid);
        }
        return importer.run(request);
    }

    private byte[] readRequest() {
        try (InputStream in = Files.newInputStream(settings.request())) {
            byte[] bytes = in.readNBytes(GraphHandoffRequestParser.MAX_BYTES + 1);
            if (bytes.length > GraphHandoffRequestParser.MAX_BYTES) {
                throw new GraphHandoffException(GraphHandoffFailure.REQUEST_INVALID);
            }
            return bytes;
        } catch (IOException error) {
            throw new GraphHandoffException(GraphHandoffFailure.REQUEST_INVALID);
        }
    }

    private FileChannel reserveResult() {
        try {
            return FileChannel.open(settings.result(), Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                    LinkOption.NOFOLLOW_LINKS), PosixFilePermissions.asFileAttribute(
                            PosixFilePermissions.fromString("rw-------")));
        } catch (IOException | RuntimeException error) {
            log.error("graph handoff import result file could not be created: {}", error.getClass().getSimpleName());
            throw new GraphHandoffAbortedException(GraphHandoffFailure.RESULT_UNAVAILABLE);
        }
    }
}
