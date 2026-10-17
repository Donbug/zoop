package com.zoop.graph.importer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

/** The real subprocess client against stand-in executables; the real CLI is exercised by the operator smoke. */
class ProcessHandoffExporterTest {
    private static final Map<String, String> PARENT = Map.of(
            "DB_URL", "jdbc:postgresql://127.0.0.1:5432/secret-db", "DB_USERNAME", "secret-user",
            "DB_PASSWORD", "secret-password", "ZOOP_AI_CLIENT_TOKEN", "secret-token", "PATH", "/evil/bin",
            "ZOOP_STATE_DIR", "/app/state", "ZOOP_AI_WORKER_STATE_DIR", "/worker/state");
    private static final Set<String> TOLERATED = Set.of("PWD", "OLDPWD", "SHLVL", "_", "__CF_USER_TEXT_ENCODING");

    @TempDir
    Path temp;
    private Path work;
    private GraphHandoffImportSettings settings;

    @BeforeEach
    void setUp() throws IOException {
        Path base = temp.toRealPath();
        work = Files.createDirectory(base.resolve("work"));
        settings = new GraphHandoffImportSettings(base.resolve("request.json"), base.resolve("result.json"),
                base.resolve("zoop-ai-handoff"), base.resolve("handoff"), base.resolve("relation"), base.resolve("extraction"),
                base.resolve("zoop-ai-ingest"), base.resolve("ingestion"), base.resolve("sources.json"),
                base.resolve("canonical.json"), base.resolve("decisions.json"), base.resolve("bindings.json"),
                base.resolve("artifacts"));
    }

    private Path script(String body) throws IOException {
        Path script = Files.writeString(work.resolve("fake-handoff-" + System.nanoTime()), "#!/bin/sh\n" + body + "\n");
        Files.setPosixFilePermissions(script, PosixFilePermissions.fromString("rwx------"));
        return script;
    }

    private ProcessHandoffExporter exporter(Path cli, Duration timeout, int maxStdout) {
        List<String> argv = new java.util.ArrayList<>(ProcessHandoffExporter.argv(settings));
        argv.set(0, cli.toString());
        return new ProcessHandoffExporter(argv, timeout, maxStdout, PARENT, "/home/operator");
    }

    private ProcessHandoffExporter exporter(Path cli) {
        return exporter(cli, Duration.ofSeconds(30), ProcessHandoffExporter.MAX_STDOUT_BYTES);
    }

    private static GraphHandoffException failure(ProcessHandoffExporter exporter) {
        return assertThrows(GraphHandoffException.class, () -> exporter.export("handoff-1"));
    }

    @Test
    void theArgumentVectorIsFixedAndTheSelectorTravelsOnStdin() {
        List<String> argv = ProcessHandoffExporter.argv(settings);

        assertEquals(List.of(settings.handoffCli().toString(), "export",
                "--state-dir", settings.handoffState().toString(),
                "--relation-state-dir", settings.relationState().toString(),
                "--extraction-state-dir", settings.extractionState().toString(),
                "--ingestion-state-dir", settings.ingestionState().toString(),
                "--sources", settings.ingestionSources().toString(),
                "--canonical", settings.canonical().toString(),
                "--decisions", settings.decisions().toString(),
                "--bindings", settings.bindings().toString()), argv);
        assertEquals("{\"schemaVersion\":\"zoop-ai-handoff-1\",\"handoffId\":\"handoff-1\"}",
                new String(ProcessHandoffExporter.selectorJson("handoff-1"), StandardCharsets.UTF_8));
    }

    @Test
    void theChildEnvironmentIsAnAllowListWithoutDatabaseCredentials() {
        Map<String, String> environment = ProcessHandoffExporter.childEnvironment(PARENT, "/home/operator");

        assertEquals(Set.of("PATH", "HOME", "LANG", "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE",
                "ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"), environment.keySet());
        assertEquals("/usr/bin:/bin", environment.get("PATH"));
        assertFalse(environment.toString().contains("secret"));
        Map<String, String> unset = new LinkedHashMap<>();
        unset.put("ZOOP_STATE_DIR", "");
        unset.put("DB_PASSWORD", "secret-password");
        assertEquals(Set.of("PATH", "HOME", "LANG", "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE"),
                ProcessHandoffExporter.childEnvironment(unset, "/home/operator").keySet());
    }

    @Test
    void aRealRunPassesExactArgumentsStdinAndOnlyTheAllowListedEnvironment() throws Exception {
        Path capture = Files.createDirectory(temp.toRealPath().resolve("capture"));
        Path cli = script("cat > '" + capture + "/stdin.json'\n"
                + "printf '%s\\n' \"$@\" > '" + capture + "/argv.txt'\n"
                + "env > '" + capture + "/env.txt'\n"
                + "printf '{\"hello\":\"world\"}'");

        byte[] output = exporter(cli).export("handoff-1");

        assertEquals("{\"hello\":\"world\"}", new String(output, StandardCharsets.UTF_8));
        assertEquals(new String(ProcessHandoffExporter.selectorJson("handoff-1"), StandardCharsets.UTF_8),
                Files.readString(capture.resolve("stdin.json")));
        List<String> expectedArgv = ProcessHandoffExporter.argv(settings);
        assertEquals(expectedArgv.subList(1, expectedArgv.size()), Files.readAllLines(capture.resolve("argv.txt")));
        Map<String, String> seen = new LinkedHashMap<>();
        for (String line : Files.readAllLines(capture.resolve("env.txt"))) {
            int split = line.indexOf('=');
            if (split > 0) {
                seen.put(line.substring(0, split), line.substring(split + 1));
            }
        }
        Set<String> keys = new HashSet<>(seen.keySet());
        keys.removeAll(TOLERATED);
        assertEquals(ProcessHandoffExporter.childEnvironment(PARENT, "/home/operator").keySet(), keys);
        assertFalse(String.join("\n", Files.readAllLines(capture.resolve("env.txt"))).contains("secret"));
    }

    @Test
    void theStructuredRefusalOfTheCliIsReportedWithItsCodeOnly() throws Exception {
        Path cli = script("cat > /dev/null\n"
                + "printf '{\"schemaVersion\":\"zoop-ai-handoff-1\",\"error\":{\"code\":\"handoff_not_ready\",\"detail\":{\"state\":\"failed\"}}}'\n"
                + "exit 2");

        GraphHandoffException failure = failure(exporter(cli));

        assertEquals(GraphHandoffFailure.HANDOFF_REFUSED, failure.failure());
        assertEquals("handoff_not_ready", failure.cliCode());
    }

    @Test
    void aWithheldHandoffIsReportedAsWithheldWithoutContent() throws Exception {
        Path cli = script("cat > /dev/null\n"
                + "printf '{\"delivery\":{\"code\":\"source_unauthorized\",\"status\":\"withheld\"},\"handoffId\":\"handoff-1\","
                + "\"publication\":\"not-published\",\"schemaVersion\":\"zoop-ai-handoff-1\",\"state\":\"ready\","
                + "\"usage\":{\"modelCalls\":0,\"providerCalls\":0}}'\n"
                + "exit 2");

        GraphHandoffException failure = failure(exporter(cli));

        assertEquals(GraphHandoffFailure.HANDOFF_WITHHELD, failure.failure());
        assertEquals("source_unauthorized", failure.cliCode());
    }

    @Test
    void anythingElseIsUnavailable() throws Exception {
        for (String body : List.of("exit 1", "printf 'not json'\nexit 2", "exit 2", "printf '{}'\nexit 3",
                "printf '{\"schemaVersion\":\"zoop-ai-handoff-1\",\"error\":{\"code\":\"x\",\"extra\":1}}'\nexit 2",
                "printf '{\"schemaVersion\":\"zoop-ai-handoff-2\",\"error\":{\"code\":\"x\"}}'\nexit 2")) {
            GraphHandoffException failure = failure(exporter(script(body)));

            assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_UNAVAILABLE, failure.failure(), body);
            assertNull(failure.cliCode());
        }
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_UNAVAILABLE,
                failure(exporter(work.resolve("does-not-exist"))).failure());
    }

    @Test
    void aSlowChildIsKilledAndAnOversizedOutputIsRefused() throws Exception {
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_UNAVAILABLE,
                failure(exporter(script("exec sleep 30"), Duration.ofMillis(400), 1024)).failure());
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_UNAVAILABLE,
                failure(exporter(script("yes x | head -c 4096"), Duration.ofSeconds(30), 1024)).failure());
    }
}
