package com.zoop.document.importer;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import com.zoop.common.json.StrictJson;
import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import tools.jackson.databind.node.ObjectNode;

/**
 * Runs the installed {@code zoop-ai-ingest export --require-store} as a fresh subprocess for every item. Nothing is cached
 * or reused, so the CLI's own check of the current source registry (grant enabled, rights known, evidence present,
 * {@code read}, {@code store} and {@code quote-display} allowed, not expired, scope unchanged) decides each import. The text
 * is persisted by this importer, so the {@code store} right is required explicitly: without the flag the export only needs
 * {@code read} and {@code quote-display}. The export document carries only the grant id and revision, so this JVM neither
 * can nor does evaluate rights itself; a CLI that does not know the flag fails (exit 2, no JSON) and the item is refused.
 * The ledger is opened read-only by the CLI and never by this JVM.
 *
 * <p>The argument vector is fixed and the selector is passed on stdin, so no request value reaches a shell or an argument.
 * The child environment is cleared and rebuilt from a short allow-list: database credentials and every other variable of
 * this process are never inherited. stdout is bounded and decoded strictly by the parser; stderr is discarded and never
 * logged; the run has a deadline after which the child is killed.
 */
public final class ProcessIngestionExporter implements IngestionExporter {
    public static final int MAX_STDOUT_BYTES = 16 * 1024 * 1024;
    public static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(120);

    private static final String SELECTOR_SCHEMA = "zoop-ingestion-s2-1";
    /** The only parent variables passed through: installed (non-checkout) S2-1 packages require them. */
    private static final List<String> PASSTHROUGH = List.of("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR");

    private final Path cli;
    private final Path stateDirectory;
    private final Path sources;
    private final Duration timeout;
    private final int maxStdoutBytes;
    private final Map<String, String> environment;

    public ProcessIngestionExporter(Path cli, Path stateDirectory, Path sources, Duration timeout, int maxStdoutBytes,
            Map<String, String> parentEnvironment, String home) {
        this.cli = cli;
        this.stateDirectory = stateDirectory;
        this.sources = sources;
        this.timeout = timeout;
        this.maxStdoutBytes = maxStdoutBytes;
        this.environment = childEnvironment(parentEnvironment, home);
    }

    public static ProcessIngestionExporter forSettings(DocumentImportSettings settings) {
        return forPaths(settings.ingestionCli(), settings.ingestionState(), settings.ingestionSources());
    }

    /** The same exporter for any operator run that owns these three validated paths (the document analysis shares it). */
    public static ProcessIngestionExporter forPaths(Path cli, Path stateDirectory, Path sources) {
        return new ProcessIngestionExporter(cli, stateDirectory, sources, DEFAULT_TIMEOUT, MAX_STDOUT_BYTES, System.getenv(),
                System.getProperty("user.home"));
    }

    /** The complete child environment: fixed values plus the two state-ownership directories if the parent has them. */
    static Map<String, String> childEnvironment(Map<String, String> parent, String home) {
        Map<String, String> child = new LinkedHashMap<>();
        child.put("PATH", "/usr/bin:/bin");
        child.put("HOME", home);
        child.put("LANG", "C.UTF-8");
        child.put("PYTHONUTF8", "1");
        child.put("PYTHONIOENCODING", "utf-8");
        child.put("PYTHONDONTWRITEBYTECODE", "1");
        for (String name : PASSTHROUGH) {
            String value = parent.get(name);
            if (value != null && !value.isEmpty()) {
                child.put(name, value);
            }
        }
        return child;
    }

    static List<String> argv(Path cli, Path stateDirectory, Path sources) {
        return List.of(cli.toString(), "export", "--state-dir", stateDirectory.toString(), "--sources",
                sources.toString(), "--require-store");
    }

    static byte[] selectorJson(Observation observation) {
        ObjectNode selector = StrictJson.newObject();
        selector.put("schemaVersion", SELECTOR_SCHEMA);
        selector.put("roundId", observation.roundId());
        selector.put("sourceId", observation.sourceId());
        selector.put("page", observation.page());
        selector.put("ordinal", observation.ordinal());
        selector.put("documentId", observation.documentId());
        selector.put("rawVersion", observation.rawVersion());
        selector.put("documentVersion", observation.documentVersion());
        return StrictJson.write(selector);
    }

    @Override
    public byte[] export(Observation observation) {
        ProcessBuilder builder = new ProcessBuilder(new ArrayList<>(argv(cli, stateDirectory, sources)));
        builder.directory(new File(System.getProperty("java.io.tmpdir")));
        builder.environment().clear();
        builder.environment().putAll(environment);
        builder.redirectError(ProcessBuilder.Redirect.DISCARD);
        Process process;
        try {
            process = builder.start();
        } catch (IOException | RuntimeException error) {
            throw unavailable();
        }
        AtomicReference<byte[]> stdout = new AtomicReference<>();
        AtomicBoolean overflow = new AtomicBoolean();
        Thread reader = new Thread(() -> {
            try (InputStream in = process.getInputStream()) {
                byte[] data = in.readNBytes(maxStdoutBytes + 1);
                if (data.length > maxStdoutBytes) {
                    overflow.set(true);
                    process.destroyForcibly();
                } else {
                    stdout.set(data);
                }
            } catch (IOException ignored) {
                // No stdout: handled as unavailable below.
            }
        }, "ingestion-export-stdout");
        reader.setDaemon(true);
        reader.start();
        try {
            try (OutputStream in = process.getOutputStream()) {
                in.write(selectorJson(observation));
            } catch (IOException ignored) {
                // The child may exit before reading; its exit status decides.
            }
            if (!process.waitFor(timeout.toMillis(), TimeUnit.MILLISECONDS)) {
                process.destroyForcibly();
                process.waitFor(5, TimeUnit.SECONDS);
                throw unavailable();
            }
            reader.join(TimeUnit.SECONDS.toMillis(5));
        } catch (InterruptedException interrupted) {
            process.destroyForcibly();
            Thread.currentThread().interrupt();
            throw unavailable();
        } finally {
            if (process.isAlive()) {
                process.destroyForcibly();
            }
        }
        byte[] output = stdout.get();
        if (overflow.get() || output == null || reader.isAlive()) {
            throw unavailable();
        }
        int exit = process.exitValue();
        if (exit == 0) {
            return output;
        }
        if (exit == 2) {
            throw refused(output);
        }
        throw unavailable();
    }

    /** Exit 2 is the CLI's structured refusal: {@code {"schemaVersion", "error": {"code"}}}. Anything else is unavailable. */
    private static DocumentImportException refused(byte[] output) {
        try {
            StrictJson.Obj root = StrictJson.parseObject(output).exactly(Set.of("schemaVersion", "error"));
            if (!IngestionExportParser.SCHEMA_VERSION.equals(root.string("schemaVersion"))) {
                return unavailable();
            }
            return DocumentImportException.ingestionRefused(root.object("error").exactly(Set.of("code")).string("code"));
        } catch (StrictJson.Malformed malformed) {
            return unavailable();
        }
    }

    private static DocumentImportException unavailable() {
        return new DocumentImportException(DocumentImportFailure.INGESTION_EXPORT_UNAVAILABLE);
    }
}
