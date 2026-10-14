package com.zoop.document.importer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;

import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** The real subprocess client against stand-in executables; the real CLI is exercised by the operator smoke. */
class ProcessIngestionExporterTest {
    private static final Observation OBSERVATION = new Observation("r1", "출처-source", 2, 5, "doc-" + "a".repeat(64),
            "b".repeat(64), "c".repeat(64));
    private static final Map<String, String> PARENT = Map.of(
            "DB_URL", "jdbc:postgresql://127.0.0.1:5432/secret-db", "DB_USERNAME", "secret-user",
            "DB_PASSWORD", "secret-password", "ZOOP_AI_CLIENT_TOKEN", "secret-token", "PATH", "/evil/bin",
            "ZOOP_STATE_DIR", "/app/state", "ZOOP_AI_WORKER_STATE_DIR", "/worker/state");
    private static final Set<String> TOLERATED = Set.of("PWD", "OLDPWD", "SHLVL", "_", "__CF_USER_TEXT_ENCODING");
    private static final String REFUSED = "{\"schemaVersion\":\"zoop-ingestion-s2-1\",\"error\":{\"code\":\"%s\"}}";

    @TempDir
    Path temp;
    private Path work;
    private Path state;
    private Path sources;

    @BeforeEach
    void setUp() throws IOException {
        work = Files.createDirectory(temp.toRealPath().resolve("work"));
        state = Files.createDirectory(temp.toRealPath().resolve("state"));
        sources = Files.writeString(temp.toRealPath().resolve("sources.json"), "{}");
    }

    private Path script(String body) throws IOException {
        Path script = Files.writeString(work.resolve("fake-ingest-" + System.nanoTime()), "#!/bin/sh\n" + body + "\n");
        Files.setPosixFilePermissions(script, PosixFilePermissions.fromString("rwx------"));
        return script;
    }

    private ProcessIngestionExporter exporter(Path cli, Duration timeout, int maxStdout) {
        return new ProcessIngestionExporter(cli, state, sources, timeout, maxStdout, PARENT, "/home/operator");
    }

    private ProcessIngestionExporter exporter(Path cli) {
        return exporter(cli, Duration.ofSeconds(30), ProcessIngestionExporter.MAX_STDOUT_BYTES);
    }

    private static DocumentImportException failure(ProcessIngestionExporter exporter) {
        return assertThrows(DocumentImportException.class, () -> exporter.export(OBSERVATION));
    }

    @Test
    void theArgumentVectorIsFixedAndTheSelectorTravelsOnStdinInS2Form() throws Exception {
        assertEquals(List.of("/x/zoop-ai-ingest", "export", "--state-dir", "/x/state", "--sources", "/x/sources.json",
                        "--require-store"),
                ProcessIngestionExporter.argv(Path.of("/x/zoop-ai-ingest"), Path.of("/x/state"), Path.of("/x/sources.json")));
        assertEquals("{\"schemaVersion\":\"zoop-ingestion-s2-1\",\"roundId\":\"r1\",\"sourceId\":\"출처-source\","
                        + "\"page\":2,\"ordinal\":5,\"documentId\":\"doc-" + "a".repeat(64) + "\",\"rawVersion\":\""
                        + "b".repeat(64) + "\",\"documentVersion\":\"" + "c".repeat(64) + "\"}",
                new String(ProcessIngestionExporter.selectorJson(OBSERVATION), StandardCharsets.UTF_8));
    }

    @Test
    void theChildEnvironmentIsAnAllowListWithoutDatabaseCredentials() {
        Map<String, String> environment = ProcessIngestionExporter.childEnvironment(PARENT, "/home/operator");

        assertEquals(Set.of("PATH", "HOME", "LANG", "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE",
                "ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"), environment.keySet());
        assertEquals("/usr/bin:/bin", environment.get("PATH"));
        assertEquals("/home/operator", environment.get("HOME"));
        assertEquals("/app/state", environment.get("ZOOP_STATE_DIR"));
        assertEquals("/worker/state", environment.get("ZOOP_AI_WORKER_STATE_DIR"));
        assertFalse(environment.toString().contains("secret"));

        Map<String, String> unset = new LinkedHashMap<>();
        unset.put("ZOOP_STATE_DIR", "");
        unset.put("DB_PASSWORD", "secret-password");
        assertEquals(Set.of("PATH", "HOME", "LANG", "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE"),
                ProcessIngestionExporter.childEnvironment(unset, "/home/operator").keySet());
    }

    @Test
    void aRealRunPassesExactArgumentsStdinAndOnlyTheAllowListedEnvironment() throws Exception {
        Path capture = Files.createDirectory(temp.toRealPath().resolve("capture"));
        Path cli = script("cat > '" + capture + "/stdin.json'\n"
                + "printf '%s\\n' \"$@\" > '" + capture + "/argv.txt'\n"
                + "env > '" + capture + "/env.txt'\n"
                + "pwd > '" + capture + "/cwd.txt'\n"
                + "printf '{\"hello\":\"world\"}'");

        byte[] output = exporter(cli).export(OBSERVATION);

        assertEquals("{\"hello\":\"world\"}", new String(output, StandardCharsets.UTF_8));
        assertArrayEqualsText(ProcessIngestionExporter.selectorJson(OBSERVATION), Files.readAllBytes(capture.resolve("stdin.json")));
        assertEquals(List.of("export", "--state-dir", state.toString(), "--sources", sources.toString(), "--require-store"),
                Files.readAllLines(capture.resolve("argv.txt")));
        Map<String, String> seen = new LinkedHashMap<>();
        for (String line : Files.readAllLines(capture.resolve("env.txt"))) {
            int split = line.indexOf('=');
            if (split > 0) {
                seen.put(line.substring(0, split), line.substring(split + 1));
            }
        }
        Set<String> keys = new HashSet<>(seen.keySet());
        keys.removeAll(TOLERATED);
        assertEquals(ProcessIngestionExporter.childEnvironment(PARENT, "/home/operator").keySet(), keys);
        assertEquals("/usr/bin:/bin", seen.get("PATH"));
        assertEquals("/home/operator", seen.get("HOME"));
        assertFalse(String.join("\n", Files.readAllLines(capture.resolve("env.txt"))).contains("secret"));
        assertEquals(Path.of(System.getProperty("java.io.tmpdir")).toRealPath(),
                Path.of(Files.readString(capture.resolve("cwd.txt")).strip()).toRealPath());
    }

    private static void assertArrayEqualsText(byte[] expected, byte[] actual) {
        assertEquals(new String(expected, StandardCharsets.UTF_8), new String(actual, StandardCharsets.UTF_8));
    }

    @Test
    void aChildThatNeverReadsStdinStillReturnsItsOutput() throws Exception {
        Path cli = script("printf '{\"ok\":true}'");

        assertEquals("{\"ok\":true}", new String(exporter(cli).export(OBSERVATION), StandardCharsets.UTF_8));
    }

    @Test
    void theCliRefusalCodeIsReportedWhenItIsPlainSnakeCase() throws Exception {
        for (String code : List.of("source_unauthorized", "ingestion_busy", "ingestion_recovery_required", "observation_not_found")) {
            Path cli = script("cat > /dev/null\nprintf '%s' '" + REFUSED.formatted(code) + "'\necho 'secret-stderr' >&2\nexit 2");
            DocumentImportException error = failure(exporter(cli));

            assertEquals(DocumentImportFailure.INGESTION_EXPORT_FAILED, error.failure());
            assertEquals(code, error.ingestionCode());
            assertFalse(String.valueOf(error.getMessage()).contains("secret"));
        }
        Path odd = script("cat > /dev/null\nprintf '%s' '" + REFUSED.formatted("Source-Unauthorized") + "'\nexit 2");
        DocumentImportException error = failure(exporter(odd));
        assertEquals(DocumentImportFailure.INGESTION_EXPORT_FAILED, error.failure());
        assertNull(error.ingestionCode());
    }

    @Test
    void anythingButAStructuredRefusalOrSuccessIsUnavailable() throws Exception {
        List<String> bodies = List.of(
                "cat > /dev/null\nprintf 'not json'\nexit 2",
                "cat > /dev/null\nprintf '%s' '{\"schemaVersion\":\"zoop-ingestion-s2-1\",\"error\":{\"code\":\"x\",\"more\":1}}'\nexit 2",
                "cat > /dev/null\nprintf '%s' '{\"schemaVersion\":\"other\",\"error\":{\"code\":\"x\"}}'\nexit 2",
                "cat > /dev/null\nprintf '%s' '" + REFUSED.formatted("source_unauthorized") + "'\nexit 1",
                "cat > /dev/null\nprintf '%s' '" + REFUSED.formatted("source_unauthorized") + "'\nexit 3",
                "cat > /dev/null\nexit 2",
                "cat > /dev/null\nkill -9 $$");
        for (String body : bodies) {
            assertEquals(DocumentImportFailure.INGESTION_EXPORT_UNAVAILABLE, failure(exporter(script(body))).failure(), body);
        }
    }

    @Test
    void oversizedStdoutIsRefusedAndTheLimitIsInclusive() throws Exception {
        Path exact = script("cat > /dev/null\nyes aaaaaaaaaaaaaaa | head -c 1024");
        assertEquals(1024, exporter(exact, Duration.ofSeconds(30), 1024).export(OBSERVATION).length);

        Path over = script("cat > /dev/null\nyes aaaaaaaaaaaaaaa | head -c 1025");
        assertEquals(DocumentImportFailure.INGESTION_EXPORT_UNAVAILABLE,
                failure(exporter(over, Duration.ofSeconds(30), 1024)).failure());
        Path endless = script("cat > /dev/null\nexec yes aaaaaaaaaaaaaaa");
        assertEquals(DocumentImportFailure.INGESTION_EXPORT_UNAVAILABLE,
                failure(exporter(endless, Duration.ofSeconds(30), 1024)).failure());
    }

    @Test
    void aChildThatOutlivesTheDeadlineIsKilled() throws Exception {
        Path cli = script("cat > /dev/null\nexec sleep 60");
        long started = System.nanoTime();

        assertEquals(DocumentImportFailure.INGESTION_EXPORT_UNAVAILABLE,
                failure(exporter(cli, Duration.ofMillis(500), 1024)).failure());

        assertTrue(Duration.ofNanos(System.nanoTime() - started).toSeconds() < 20);
    }

    @Test
    void aMissingOrNonExecutableCliIsUnavailable() throws Exception {
        assertEquals(DocumentImportFailure.INGESTION_EXPORT_UNAVAILABLE,
                failure(exporter(work.resolve("does-not-exist"))).failure());
        Path plain = Files.writeString(work.resolve("plain"), "#!/bin/sh\nexit 0\n");
        assertEquals(DocumentImportFailure.INGESTION_EXPORT_UNAVAILABLE, failure(exporter(plain)).failure());
    }

    @Test
    void theClientNeverWritesIntoTheIngestionStateDirectory() throws Exception {
        Files.writeString(state.resolve("ingestion.sqlite3"), "ledger");
        Files.writeString(state.resolve("ingestion.lock"), "");
        List<String> before = listing(state);
        Path cli = script("cat > /dev/null\nprintf '{}'");

        exporter(cli).export(OBSERVATION);

        assertEquals(before, listing(state));
    }

    private static List<String> listing(Path directory) throws IOException {
        List<String> entries = new ArrayList<>();
        try (Stream<Path> files = Files.list(directory)) {
            for (Path file : files.sorted().toList()) {
                entries.add(file.getFileName() + ":" + Files.size(file) + ":" + Files.getLastModifiedTime(file).toMillis());
            }
        }
        return entries;
    }
}
