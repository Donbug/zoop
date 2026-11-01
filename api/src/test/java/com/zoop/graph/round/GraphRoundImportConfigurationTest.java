package com.zoop.graph.round;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
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
import com.zoop.graph.importer.GraphHandoffRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.Mockito;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.boot.test.context.ConfigDataApplicationContextInitializer;
import org.springframework.transaction.support.TransactionOperations;

/**
 * The bridge's configuration in a minimal web context: it exists only with {@code zoop.graph.round.enabled=true} and fails
 * closed, naming the setting, when the snapshot source, the read client or the S2-1 CLI settings are missing, or when
 * {@code import-source=http} has no observation export client or keeps a CLI setting.
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

    private static final String[] EXPORT_CLIENT = {
            "ZOOP_AI_OBSERVATION_EXPORT_CLIENT_ENABLED", "true",
            "ZOOP_AI_OBSERVATION_EXPORT_CLIENT_BASE_URL", "https://ai.internal.example",
            "ZOOP_AI_OBSERVATION_EXPORT_CLIENT_TOKEN", "export-token-0123456789abcdefghijklmnopqrstuvwxyz"};

    /** The ECS profile: import-source http, the export client, no S2-1 CLI setting; {@code extra} applies last. */
    private String[] observationHttp(String... extra) {
        List<String> changes = new ArrayList<>(Arrays.asList("ZOOP_GRAPH_ROUND_IMPORT_SOURCE", "http",
                "ZOOP_GRAPH_ROUND_INGESTION_CLI", null, "ZOOP_GRAPH_ROUND_INGESTION_STATE_DIR", null,
                "ZOOP_GRAPH_ROUND_INGESTION_SOURCES", null));
        changes.addAll(Arrays.asList(EXPORT_CLIENT));
        changes.addAll(Arrays.asList(extra));
        return with(changes.toArray(String[]::new));
    }

    @Test
    void theHttpImportSourceUsesTheObservationExportClientWithoutTheS2Cli() {
        runner().withUserConfiguration(AiObservationExportClientConfiguration.class).withPropertyValues(observationHttp())
                .run(context -> {
                    assertNull(context.getStartupFailure());
                    assertNotNull(context.getBean(GraphRoundImportBridge.class));
                });
    }

    @Test
    void theHttpImportSourceWithoutTheClientOrWithACliSettingFailsClosedWhileCliIgnoresTheClient() {
        runner().withUserConfiguration(AiObservationExportClientConfiguration.class)
                .withPropertyValues(observationHttp("ZOOP_AI_OBSERVATION_EXPORT_CLIENT_ENABLED", "false")).run(context -> {
                    Throwable failure = configurationFailure(context.getStartupFailure());
                    assertNotNull(failure);
                    assertTrue(failure.getMessage().startsWith("zoop.graph.round.import-source "), failure.getMessage());
                    assertTrue(failure.getMessage().contains("zoop.ai.observation-export-client.enabled"), failure.getMessage());
                });
        String[][] cliSettings = {
                {"ZOOP_GRAPH_ROUND_INGESTION_CLI", valid.get("ZOOP_GRAPH_ROUND_INGESTION_CLI"), "zoop.graph.round.ingestion-cli "},
                {"ZOOP_GRAPH_ROUND_INGESTION_STATE_DIR", valid.get("ZOOP_GRAPH_ROUND_INGESTION_STATE_DIR"),
                        "zoop.graph.round.ingestion-state-dir "},
                {"ZOOP_GRAPH_ROUND_INGESTION_SOURCES", valid.get("ZOOP_GRAPH_ROUND_INGESTION_SOURCES"),
                        "zoop.graph.round.ingestion-sources "},
        };
        for (String[] c : cliSettings) {
            runner().withUserConfiguration(AiObservationExportClientConfiguration.class)
                    .withPropertyValues(observationHttp(c[0], c[1])).run(context -> {
                        Throwable failure = configurationFailure(context.getStartupFailure());
                        assertNotNull(failure, c[0]);
                        assertTrue(failure.getMessage().startsWith(c[2]), failure.getMessage());
                        assertTrue(failure.getMessage().contains("import-source=http"), failure.getMessage());
                        assertTrue(!failure.getMessage().contains(temp.toString()), failure.getMessage());
                    });
        }
        // An enabled export client does not change cli: the S2-1 CLI settings stay required and are used.
        runner().withUserConfiguration(AiObservationExportClientConfiguration.class)
                .withPropertyValues(with(EXPORT_CLIENT))
                .run(context -> {
                    assertNull(context.getStartupFailure());
                    assertNotNull(context.getBean(GraphRoundImportBridge.class));
                });
    }
}
