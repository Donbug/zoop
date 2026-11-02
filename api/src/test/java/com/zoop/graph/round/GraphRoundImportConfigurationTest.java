package com.zoop.graph.round;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Clock;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import javax.sql.DataSource;

import com.zoop.ai.config.AiHandoffReadClientConfiguration;
import com.zoop.ai.config.AiObservationExportClientConfiguration;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.ai.observation.ObservationExportClient;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.mockito.Mockito;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.boot.test.context.ConfigDataApplicationContextInitializer;
import org.springframework.transaction.support.TransactionOperations;

/**
 * The bridge's configuration in a minimal web context: it exists only with {@code zoop.graph.round.enabled=true} and fails
 * closed, naming the setting, when a required source setting is missing or HTTP retains a nonblank CLI setting.
 */
class GraphRoundImportConfigurationTest {
    @TempDir
    Path temp;
    private final Map<String, String> valid = new LinkedHashMap<>();

    @BeforeEach
    void setUp() throws IOException {
        Path base = temp.toRealPath();
        Path cli = Files.writeString(base.resolve("zoop-ai-ingest"), "#!/bin/sh\n");
        Files.setPosixFilePermissions(cli, PosixFilePermissions.fromString("rwx------"));
        valid.put("ZOOP_GRAPH_ROUND_ENABLED", "true");
        valid.put("ZOOP_GRAPH_SNAPSHOT_SOURCE", "artifact");
        valid.put("ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT", Files.createDirectory(base.resolve("artifacts")).toString());
        valid.put("ZOOP_GRAPH_ROUND_INGESTION_CLI", cli.toString());
        valid.put("ZOOP_GRAPH_ROUND_INGESTION_STATE_DIR", Files.createDirectory(base.resolve("ingestion")).toString());
        valid.put("ZOOP_GRAPH_ROUND_INGESTION_SOURCES", Files.writeString(base.resolve("sources.json"), "{}").toString());
        valid.put("ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED", "true");
        valid.put("ZOOP_AI_HANDOFF_READ_CLIENT_BASE_URL", "https://ai.internal.example");
        valid.put("ZOOP_AI_HANDOFF_READ_CLIENT_TOKEN", "read-token-0123456789abcdefghijklmnopqrstuvwxyz");
    }

    private static void isolate(ConfigurableApplicationContext context) {
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
    }

    private WebApplicationContextRunner runner() {
        return new WebApplicationContextRunner()
                .withInitializer(GraphRoundImportConfigurationTest::isolate)
                .withInitializer(new ConfigDataApplicationContextInitializer())
                .withBean(DocumentRegistryRepository.class, () -> Mockito.mock(DocumentRegistryRepository.class))
                .withBean(GraphHandoffRepository.class, () -> Mockito.mock(GraphHandoffRepository.class))
                .withBean(GraphRoundRepository.class, InMemoryGraphRoundRepository::new)
                .withBean(TransactionOperations.class, TransactionOperations::withoutTransaction)
                .withBean(DataSource.class, () -> Mockito.mock(DataSource.class))
                .withBean(Clock.class, Clock::systemUTC)
                .withUserConfiguration(AiHandoffReadClientConfiguration.class, GraphRoundImportConfiguration.class);
    }

    private String[] with(String... extra) {
        Map<String, String> changed = new LinkedHashMap<>(valid);
        for (int i = 0; i + 1 < extra.length; i += 2) {
            if (extra[i + 1] == null) changed.remove(extra[i]);
            else changed.put(extra[i], extra[i + 1]);
        }
        return changed.entrySet().stream().map(entry -> entry.getKey() + "=" + entry.getValue()).toArray(String[]::new);
    }

    private static Throwable configurationFailure(Throwable failure) {
        for (Throwable cause = failure; cause != null; cause = cause.getCause()) {
            if (cause instanceof GraphRoundConfigurationException) return cause;
        }
        return null;
    }

    @Test
    void disabledRegistersNothingAndNeedsNoSetting() {
        runner().withPropertyValues("ZOOP_GRAPH_ROUND_ENABLED=false").run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(GraphRoundImportBridge.class).isEmpty());
        });
        new ApplicationContextRunner().withInitializer(new ConfigDataApplicationContextInitializer())
                .withUserConfiguration(GraphRoundImportConfiguration.class).withPropertyValues(with()).run(context -> {
                    assertNull(context.getStartupFailure());
                    assertTrue(context.getBeansOfType(GraphRoundImportBridge.class).isEmpty(), "web application only");
                });
    }

    @Test
    void enabledWithTheSnapshotRootTheReadClientAndTheCliSettingsCreatesTheBridge() {
        runner().withPropertyValues(with()).run(context -> {
            assertNull(context.getStartupFailure());
            assertNotNull(context.getBean(GraphRoundImportBridge.class));
        });
    }

    private static final String[] EXPORT_CLIENT = {
            "ZOOP_AI_OBSERVATION_EXPORT_CLIENT_ENABLED", "true",
            "ZOOP_AI_OBSERVATION_EXPORT_CLIENT_BASE_URL", "https://ai.internal.example",
            "ZOOP_AI_OBSERVATION_EXPORT_CLIENT_TOKEN", "export-token-0123456789abcdefghijklmnopqrstuvwxyz"};

    private String[] observationHttp(String... extra) {
        List<String> changes = new ArrayList<>(Arrays.asList("ZOOP_GRAPH_ROUND_IMPORT_SOURCE", "http",
                "ZOOP_GRAPH_ROUND_INGESTION_CLI", null, "ZOOP_GRAPH_ROUND_INGESTION_STATE_DIR", null,
                "ZOOP_GRAPH_ROUND_INGESTION_SOURCES", null));
        changes.addAll(Arrays.asList(EXPORT_CLIENT));
        changes.addAll(Arrays.asList(extra));
        return with(changes.toArray(String[]::new));
    }

    @ParameterizedTest
    @CsvSource({
            "ZOOP_GRAPH_ROUND_INGESTION_CLI,ingestion-cli",
            "ZOOP_GRAPH_ROUND_INGESTION_STATE_DIR,ingestion-state-dir",
            "ZOOP_GRAPH_ROUND_INGESTION_SOURCES,ingestion-sources"
    })
    void httpRejectsEachResidualCliSettingWithoutLeakingItsValue(String environmentKey, String setting) {
        runner().withUserConfiguration(AiObservationExportClientConfiguration.class)
                .withPropertyValues(observationHttp(environmentKey, valid.get(environmentKey))).run(context -> {
                    Throwable failure = configurationFailure(context.getStartupFailure());
                    assertNotNull(failure, environmentKey);
                    assertTrue(failure.getMessage().startsWith("zoop.graph.round." + setting + " "), failure.getMessage());
                    assertTrue(failure.getMessage().contains("import-source=http"), failure.getMessage());
                    assertTrue(!failure.getMessage().contains(temp.toString()), failure.getMessage());
                });
    }

    @Test
    void httpRequiresTheEnabledRealObservationClient() {
        runner().withUserConfiguration(AiObservationExportClientConfiguration.class)
                .withPropertyValues(observationHttp("ZOOP_AI_OBSERVATION_EXPORT_CLIENT_ENABLED", "false")).run(context -> {
                    Throwable failure = configurationFailure(context.getStartupFailure());
                    assertNotNull(failure);
                    assertTrue(failure.getMessage().startsWith("zoop.graph.round.import-source "), failure.getMessage());
                    assertTrue(failure.getMessage().contains("zoop.ai.observation-export-client.enabled"), failure.getMessage());
                });
    }

    @Test
    void cliStillRequiresItsExecutableWhenTheHttpClientIsEnabled() {
        runner().withUserConfiguration(AiObservationExportClientConfiguration.class).withPropertyValues(with(EXPORT_CLIENT))
                .run(context -> {
                    assertNull(context.getStartupFailure());
                    assertNotNull(context.getBean(GraphRoundImportBridge.class));
                });
        runner().withUserConfiguration(AiObservationExportClientConfiguration.class)
                .withPropertyValues(with(EXPORT_CLIENT))
                .withPropertyValues("ZOOP_GRAPH_ROUND_INGESTION_CLI=").run(context -> {
                    Throwable failure = configurationFailure(context.getStartupFailure());
                    assertNotNull(failure);
                    assertTrue(failure.getMessage().startsWith("zoop.graph.round.ingestion-cli "), failure.getMessage());
                });
    }

    @Test
    void httpContextExportsAnObservationThroughTheConfiguredClient() throws IOException {
        var selector = new ObservationExportClient.Selector("round-1", "source-a", 0, 1, "doc-" + "a".repeat(64),
                "b".repeat(64), "c".repeat(64));
        byte[] exported = ("""
                {"schemaVersion":"zoop-ingestion-s2-1","observation":{"roundId":"round-1","sourceId":"source-a",
                "page":0,"ordinal":1,"documentId":"%s","rawVersion":"%s","documentVersion":"%s"}}
                """.formatted(selector.documentId(), selector.rawVersion(), selector.documentVersion()))
                .getBytes(StandardCharsets.UTF_8);
        List<String> requests = new ArrayList<>();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/v1/observations/export", exchange -> {
            requests.add(exchange.getRequestMethod() + " " + exchange.getRequestURI().getPath());
            requests.add(exchange.getRequestHeaders().getFirst("Authorization"));
            requests.add(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.getResponseHeaders().set("X-Request-ID", exchange.getRequestHeaders().getFirst("X-Request-ID"));
            exchange.sendResponseHeaders(200, exported.length);
            try (var body = exchange.getResponseBody()) {
                body.write(exported);
            } finally {
                exchange.close();
            }
        });
        server.start();
        try {
            runner().withUserConfiguration(AiObservationExportClientConfiguration.class)
                    .withPropertyValues(observationHttp("ZOOP_AI_OBSERVATION_EXPORT_CLIENT_BASE_URL",
                            "http://127.0.0.1:" + server.getAddress().getPort(),
                            "ZOOP_GRAPH_ROUND_INGESTION_CLI", " ",
                            "ZOOP_GRAPH_ROUND_INGESTION_STATE_DIR", " ",
                            "ZOOP_GRAPH_ROUND_INGESTION_SOURCES", " ")).run(context -> {
                        assertNull(context.getStartupFailure());
                        assertNotNull(context.getBean(GraphRoundImportBridge.class));
                        assertArrayEquals(exported, context.getBean(ObservationExportClient.class).export(selector));
                    });
            assertEquals("POST /internal/v1/observations/export", requests.get(0));
            assertEquals("Bearer " + EXPORT_CLIENT[5], requests.get(1));
            var request = tools.jackson.databind.json.JsonMapper.builder().build().readTree(requests.get(2));
            assertEquals(selector.documentId(), request.get("documentId").stringValue());
            assertEquals(selector.documentVersion(), request.get("documentVersion").stringValue());
            assertEquals(3, requests.size());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void aMissingSnapshotSourceReadClientOrCliSettingFailsStartupNamingTheSetting() {
        String[][] cases = {
                {"ZOOP_GRAPH_SNAPSHOT_SOURCE", "fixture", "zoop.graph.round.enabled "},
                {"ZOOP_GRAPH_SNAPSHOT_SOURCE", "none", "zoop.graph.round.enabled "},
                {"ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT", temp.resolve("missing").toString(), "zoop.graph.round.enabled "},
                {"ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED", "false", "zoop.graph.round.enabled "},
                {"ZOOP_GRAPH_ROUND_INGESTION_CLI", temp.resolve("missing").toString(), "zoop.graph.round.ingestion-cli "},
                {"ZOOP_GRAPH_ROUND_INGESTION_STATE_DIR", "", "zoop.graph.round.ingestion-state-dir "},
                {"ZOOP_GRAPH_ROUND_INGESTION_SOURCES", "relative.json", "zoop.graph.round.ingestion-sources "},
                {"ZOOP_GRAPH_ROUND_IMPORT_SOURCE", "grpc", "zoop.graph.round.import-source "},
                {"ZOOP_GRAPH_ROUND_OPERATOR", "operator:x", "zoop.graph.round.operator "},
        };
        for (String[] c : cases) {
            runner().withPropertyValues(with(c[0], c[1])).run(context -> {
                Throwable failure = configurationFailure(context.getStartupFailure());
                assertNotNull(failure, c[0] + "=" + c[1]);
                assertTrue(failure.getMessage().startsWith(c[2]), failure.getMessage());
                assertTrue(!failure.getMessage().contains(temp.toString()), failure.getMessage());
            });
        }
    }
}
