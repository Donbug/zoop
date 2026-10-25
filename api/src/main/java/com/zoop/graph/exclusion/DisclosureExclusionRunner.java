package com.zoop.graph.exclusion;

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

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;

/**
 * The operator entry point, like the graph import's: runs once at startup when {@code zoop.disclosure-exclusion.enabled=true} in a
 * non-web application. It reserves the result file exclusively (an existing file is never overwritten, {@code 0600}), reads and
 * validates the request, runs it, writes the result and, when it failed, ends with an exception so the process exits non-zero. A
 * reserved but empty result file, like {@code outcome_unknown}, means the outcome is unknown: re-run the SAME request file (same
 * {@code requestId}) with a new result path. If the first run committed, the re-run returns its recorded result
 * ({@code replayed: true}) and changes nothing; a new decision needs a new {@code requestId}.
 */
public final class DisclosureExclusionRunner implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(DisclosureExclusionRunner.class);

    private final Path request;
    private final Path result;
    private final ExclusionRequestParser parser;
    private final DisclosureExclusionService service;

    public DisclosureExclusionRunner(Path request, Path result, ExclusionRequestParser parser, DisclosureExclusionService service) {
        this.request = request;
        this.result = result;
        this.parser = parser;
        this.service = service;
    }

    @Override
    public void run(ApplicationArguments arguments) {
        FileChannel file = reserveResult();
        ExclusionResult outcome;
        try {
            outcome = execute();
        } catch (RuntimeException unexpected) {
            log.error("disclosure exclusion failed unexpectedly: {}", unexpected.getClass().getName());
            outcome = ExclusionResult.failed(null, new ExclusionException(ExclusionFailure.INTERNAL_ERROR));
        }
        try (file) {
            ByteBuffer buffer = ByteBuffer.wrap(ExclusionResultWriter.toBytes(outcome));
            while (buffer.hasRemaining()) {
                file.write(buffer);
            }
            file.force(true);
        } catch (IOException error) {
            log.error("disclosure exclusion result file could not be written: {}", error.getClass().getSimpleName());
            throw new ExclusionAbortedException(ExclusionFailure.RESULT_UNAVAILABLE);
        }
        if (!outcome.succeeded()) {
            throw new ExclusionAbortedException(outcome.failure().failure());
        }
    }

    private ExclusionResult execute() {
        ExclusionRequest parsed;
        try {
            parsed = parser.parse(readRequest());
        } catch (ExclusionException invalid) {
            log.warn("disclosure exclusion request rejected: {}", invalid.failure().code());
            return ExclusionResult.failed(null, invalid);
        }
        return service.run(parsed);
    }

    private byte[] readRequest() {
        try (InputStream in = Files.newInputStream(request)) {
            byte[] bytes = in.readNBytes(ExclusionRequestParser.MAX_BYTES + 1);
            if (bytes.length > ExclusionRequestParser.MAX_BYTES) throw new ExclusionException(ExclusionFailure.REQUEST_INVALID);
            return bytes;
        } catch (IOException error) {
            throw new ExclusionException(ExclusionFailure.REQUEST_INVALID);
        }
    }

    private FileChannel reserveResult() {
        try {
            return FileChannel.open(result, Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                    LinkOption.NOFOLLOW_LINKS), PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        } catch (IOException | RuntimeException error) {
            log.error("disclosure exclusion result file could not be created: {}", error.getClass().getSimpleName());
            throw new ExclusionAbortedException(ExclusionFailure.RESULT_UNAVAILABLE);
        }
    }

    /** Ends the startup run with a non-zero exit and the failure code only. */
    public static final class ExclusionAbortedException extends RuntimeException {
        public ExclusionAbortedException(ExclusionFailure failure) {
            super("disclosure exclusion failed: " + failure.code());
        }
    }
}
