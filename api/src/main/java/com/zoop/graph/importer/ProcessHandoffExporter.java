package com.zoop.graph.importer;

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
import tools.jackson.databind.node.ObjectNode;

/**
 * Runs the installed {@code zoop-ai-handoff export} as a fresh subprocess. Nothing is cached or reused: the CLI re-validates
 * every pinned authority NOW (operator files byte-identical to the manifest, every S3 job ready and bound to its S2 upstream,
 * grants and rights, the used review revisions, the rebuilt content digest) and answers {@code delivery.status=current} with the
 * frozen manifest and bundle, or a content-free {@code withheld} result. The export is the CURRENT projection, never the stored
 * artifact file. It does not check the {@code store} right: the importer persists quotes, so it asks the S2-1 CLI for that
 * separately, once per observation.
 *
 * <p>The argument vector is fixed and the selector is passed on stdin, so no request value reaches a shell or an argument. The
 * child environment is cleared and rebuilt from a short allow-list: database credentials and every other variable of this process
 * are never inherited. stdout is bounded and decoded strictly by the parser; stderr is discarded and never logged; the run has a
 * deadline after which the child is killed. No model, provider or network call happens in the CLI.
 */
public final class ProcessHandoffExporter implements HandoffExporter {
    public static final String SCHEMA_VERSION = "zoop-ai-handoff-1";
    /** The whole export envelope is bounded by the CLI at 8 MiB (bundle at most 6 MiB). */
    public static final int MAX_STDOUT_BYTES = 8 * 1024 * 1024;
    public static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(300);

    /** The only parent variables passed through: installed (non-checkout) pipeline packages require them. */
    private static final List<String> PASSTHROUGH = List.of("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR");

    private final List<String> argv;
    private final Duration timeout;
    private final int maxStdoutBytes;
    private final Map<String, String> environment;

    public ProcessHandoffExporter(List<String> argv, Duration timeout, int maxStdoutBytes,
            Map<String, String> parentEnvironment, String home) {
        this.argv = List.copyOf(argv);
        this.timeout = timeout;
        this.maxStdoutBytes = maxStdoutBytes;
        this.environment = childEnvironment(parentEnvironment, home);
    }

    public static ProcessHandoffExporter forSettings(GraphHandoffImportSettings settings) {
        return new ProcessHandoffExporter(argv(settings), DEFAULT_TIMEOUT, MAX_STDOUT_BYTES, System.getenv(),
                System.getProperty("user.home"));
    }

    static List<String> argv(GraphHandoffImportSettings settings) {
        return List.of(settings.handoffCli().toString(), "export",
                "--state-dir", settings.handoffState().toString(),
                "--relation-state-dir", settings.relationState().toString(),
                "--extraction-state-dir", settings.extractionState().toString(),
                "--ingestion-state-dir", settings.ingestionState().toString(),
                "--sources", settings.ingestionSources().toString(),
                "--canonical", settings.canonical().toString(),
                "--decisions", settings.decisions().toString(),
                "--bindings", settings.bindings().toString());
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

    static byte[] selectorJson(String handoffId) {
        ObjectNode selector = StrictJson.newObject();
        selector.put("schemaVersion", SCHEMA_VERSION);
        selector.put("handoffId", handoffId);
        return StrictJson.write(selector);
    }

    @Override
    public byte[] export(String handoffId) {
        ProcessBuilder builder = new ProcessBuilder(new ArrayList<>(argv));
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
        }, "handoff-export-stdout");
        reader.setDaemon(true);
        reader.start();
        try {
            try (OutputStream in = process.getOutputStream()) {
                in.write(selectorJson(handoffId));
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

    /**
     * Exit 2 is the CLI's structured refusal: either {@code {"schemaVersion", "error": {"code"[, "detail"]}}} or the content-free
     * withheld result {@code {"schemaVersion", "handoffId", "state", "publication", "delivery": {"status": "withheld", "code"},
     * "usage"}}. Anything else is unavailable.
     */
    private static GraphHandoffException refused(byte[] output) {
        try {
            StrictJson.Obj root = StrictJson.parseObject(output);
            if (root.has("error")) {
                root.exactly(Set.of("schemaVersion", "error"));
                if (!SCHEMA_VERSION.equals(root.string("schemaVersion"))) {
                    return unavailable();
                }
                return GraphHandoffException.handoffRefused(
                        root.object("error").keys(Set.of("code"), Set.of("detail")).string("code"));
            }
            root.exactly(Set.of("schemaVersion", "handoffId", "state", "publication", "delivery", "usage"));
            if (!SCHEMA_VERSION.equals(root.string("schemaVersion"))) {
                return unavailable();
            }
            StrictJson.Obj delivery = root.object("delivery").exactly(Set.of("status", "code"));
            if (!"withheld".equals(delivery.string("status"))) {
                return unavailable();
            }
            return GraphHandoffException.handoffWithheld(delivery.string("code"));
        } catch (StrictJson.Malformed malformed) {
            return unavailable();
        }
    }

    private static GraphHandoffException unavailable() {
        return new GraphHandoffException(GraphHandoffFailure.HANDOFF_EXPORT_UNAVAILABLE);
    }
}
