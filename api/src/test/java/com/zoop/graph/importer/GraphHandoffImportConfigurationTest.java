package com.zoop.graph.importer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Clock;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.zoop.ai.config.AiHandoffReadClientConfiguration;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.service.InMemoryDocumentRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.test.context.ConfigDataApplicationContextInitializer;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.transaction.support.TransactionOperations;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The real configuration class in a minimal context (no DB, no web server, no component scan). Settings are supplied under their
 * documented {@code ZOOP_*} names and read through the real {@code application.yml}; the shell environment and JVM system
 * properties are removed so only the synthetic values below can reach it.
 */
class GraphHandoffImportConfigurationTest {
    @TempDir
    Path temp;
    private Path base;
    private final Map<String, String> valid = new LinkedHashMap<>();

    @BeforeEach
    void setUp() throws IOException {
        base = temp.toRealPath();
        Path handoffCli = executable("zoop-ai-handoff");
        Path ingestionCli = executable("zoop-ai-ingest");
        valid.put("ZOOP_GRAPH_HANDOFF_IMPORT_ENABLED", "true");
        valid.put("ZOOP_GRAPH_HANDOFF_IMPORT_REQUEST", Files.writeString(base.resolve("request.json"), "{}").toString());
        valid.put("ZOOP_GRAPH_HANDOFF_IMPORT_RESULT", base.resolve("result.json").toString());
        valid.put("ZOOP_HANDOFF_CLI", handoffCli.toString());
        valid.put("ZOOP_HANDOFF_STATE_DIR", Files.createDirectory(base.resolve("handoff")).toString());
        valid.put("ZOOP_RELATION_STATE_DIR", Files.createDirectory(base.resolve("relation")).toString());
        valid.put("ZOOP_EXTRACTION_STATE_DIR", Files.createDirectory(base.resolve("extraction")).toString());
        valid.put("ZOOP_INGESTION_CLI", ingestionCli.toString());
        valid.put("ZOOP_INGESTION_STATE_DIR", Files.createDirectory(base.resolve("ingestion")).toString());
        valid.put("ZOOP_INGESTION_SOURCES", Files.writeString(base.resolve("sources.json"), "{}").toString());
        valid.put("ZOOP_HANDOFF_CANONICAL", Files.writeString(base.resolve("canonical.json"), "{}").toString());
        valid.put("ZOOP_HANDOFF_DECISIONS", Files.writeString(base.resolve("decisions.json"), "{}").toString());
        valid.put("ZOOP_HANDOFF_BINDINGS", Files.writeString(base.resolve("bindings.json"), "{}").toString());
        valid.put("ZOOP_ARTIFACT_ROOT", Files.createDirectory(base.resolve("artifacts")).toString());
    }

    private Path executable(String name) throws IOException {
        Path cli = Files.writeString(base.resolve(name), "#!/bin/sh\n");
        Files.setPosixFilePermissions(cli, PosixFilePermissions.fromString("rwx------"));
        return cli;
    }

    private static void isolate(ConfigurableApplicationContext context) {
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
    }

    private ApplicationContextRunner runner() {
        return new ApplicationContextRunner()
                .withInitializer(GraphHandoffImportConfigurationTest::isolate)
                .withInitializer(new ConfigDataApplicationContextInitializer())
                .withBean(DocumentRegistryRepository.class, InMemoryDocumentRegistry::new)
                .withBean(GraphHandoffRepository.class, () -> new InMemoryGraphHandoffRepository("none", 0))
                .withBean(TransactionOperations.class, TransactionOperations::withoutTransaction)
                .withBean(Clock.class, Clock::systemUTC)
                .withUserConfiguration(GraphHandoffImportConfiguration.class);
    }

    private WebApplicationContextRunner webRunner() {
        return new WebApplicationContextRunner()
                .withInitializer(GraphHandoffImportConfigurationTest::isolate)
                .withInitializer(new ConfigDataApplicationContextInitializer())
                .withBean(DocumentRegistryRepository.class, InMemoryDocumentRegistry::new)
                .withBean(GraphHandoffRepository.class, () -> new InMemoryGraphHandoffRepository("none", 0))
                .withBean(TransactionOperations.class, TransactionOperations::withoutTransaction)
                .withBean(Clock.class, Clock::systemUTC)
                .withUserConfiguration(GraphHandoffImportConfiguration.class);
    }

    private String[] values() {
        return valid.entrySet().stream().map(entry -> entry.getKey() + "=" + entry.getValue()).toArray(String[]::new);
    }

    private String[] with(String name, String value) {
        Map<String, String> changed = new LinkedHashMap<>(valid);
        changed.put(name, value);
        return changed.entrySet().stream().map(entry -> entry.getKey() + "=" + entry.getValue()).toArray(String[]::new);
    }

    private static Throwable configurationFailure(Throwable failure) {
        for (Throwable cause = failure; cause != null; cause = cause.getCause()) {
            if (cause instanceof GraphHandoffImportConfigurationException) {
                return cause;
            }
        }
        return null;
    }

    @Test
    void unconfiguredStartsWithoutAnyImportSettingAndWithoutABean() {
        runner().run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(GraphHandoffRunner.class).isEmpty());
            assertTrue(context.getBeansOfType(GraphHandoffImportSettings.class).isEmpty());
            assertTrue(context.getBeansOfType(ArtifactFileStore.class).isEmpty());
        });
    }

    @Test
    void disabledIgnoresEverythingElse() {
        runner().withPropertyValues("ZOOP_GRAPH_HANDOFF_IMPORT_ENABLED=false", "ZOOP_GRAPH_HANDOFF_IMPORT_REQUEST=relative",
                "ZOOP_ARTIFACT_ROOT=not/absolute").run(context -> {
                    assertNull(context.getStartupFailure());
                    assertTrue(context.getBeansOfType(GraphHandoffRunner.class).isEmpty());
                });
    }

    @Test
    void inheritedEnvironmentAndSystemPropertiesCannotActivateTheImport() {
        System.setProperty("zoop.graph-handoff-import.enabled", "true");
        System.setProperty("ZOOP_GRAPH_HANDOFF_IMPORT_ENABLED", "true");
        try {
            runner().run(context -> {
                assertNull(context.getStartupFailure());
                assertTrue(context.getBeansOfType(GraphHandoffRunner.class).isEmpty());
            });
        } finally {
            System.clearProperty("zoop.graph-handoff-import.enabled");
            System.clearProperty("ZOOP_GRAPH_HANDOFF_IMPORT_ENABLED");
        }
    }

    @Test
    void enabledWithValidSettingsInANonWebContextCreatesTheOperatorRunner() {
        runner().withPropertyValues(values()).run(context -> {
            assertNull(context.getStartupFailure());
            assertNotNull(context.getBean(GraphHandoffRunner.class));
            assertNotNull(context.getBean(ArtifactFileStore.class));
            GraphHandoffImportSettings settings = context.getBean(GraphHandoffImportSettings.class);
            assertEquals(base.resolve("result.json"), settings.result());
            assertEquals(base.resolve("artifacts"), settings.artifactRoot());
            assertEquals(base.resolve("sources.json"), settings.ingestionSources());
            assertEquals(base.resolve("ingestion"), settings.ingestionState());
            assertEquals("GraphHandoffImportProperties[enabled=true, handoffSource=cli]",
                    context.getBean(GraphHandoffImportProperties.class).toString());
        });
    }

    @Test
    void enabledFailsStartupClosedForABadSettingNamingTheSettingNotItsValue() {
        String[][] bad = {
                {"ZOOP_GRAPH_HANDOFF_IMPORT_REQUEST", "", "request"},
                {"ZOOP_GRAPH_HANDOFF_IMPORT_REQUEST", "relative/request.json", "request"},
                {"ZOOP_GRAPH_HANDOFF_IMPORT_REQUEST", "MISSING", "request"},
                {"ZOOP_GRAPH_HANDOFF_IMPORT_RESULT", "", "result"},
                {"ZOOP_GRAPH_HANDOFF_IMPORT_RESULT", "EXISTING", "result"},
                {"ZOOP_HANDOFF_CLI", "", "handoff-cli"},
                {"ZOOP_HANDOFF_CLI", "MISSING", "handoff-cli"},
                {"ZOOP_HANDOFF_STATE_DIR", "MISSING", "handoff-state-dir"},
                {"ZOOP_RELATION_STATE_DIR", "MISSING", "relation-state-dir"},
                {"ZOOP_EXTRACTION_STATE_DIR", "MISSING", "extraction-state-dir"},
                {"ZOOP_INGESTION_CLI", "MISSING", "ingestion-cli"},
                {"ZOOP_INGESTION_STATE_DIR", "MISSING", "ingestion-state-dir"},
                {"ZOOP_INGESTION_SOURCES", "MISSING", "ingestion-sources"},
                {"ZOOP_HANDOFF_CANONICAL", "MISSING", "canonical"},
                {"ZOOP_HANDOFF_DECISIONS", "MISSING", "decisions"},
                {"ZOOP_HANDOFF_BINDINGS", "MISSING", "bindings"},
                {"ZOOP_ARTIFACT_ROOT", "", "artifact-root"},
                {"ZOOP_ARTIFACT_ROOT", "MISSING", "artifact-root"},
                {"ZOOP_ARTIFACT_ROOT", "LEDGER", "artifact-root"}};
        for (String[] entry : bad) {
            String value = switch (entry[1]) {
                case "MISSING" -> base.resolve("missing-" + entry[2]).toString();
                case "EXISTING" -> existingResult();
                case "LEDGER" -> base.resolve("relation").toString();
                default -> entry[1];
            };
            runner().withPropertyValues(with(entry[0], value)).run(context -> {
                Throwable failure = configurationFailure(context.getStartupFailure());
                assertNotNull(failure, entry[0] + "=" + entry[1]);
                assertTrue(failure.getMessage().startsWith("zoop.graph-handoff-import." + entry[2] + " "), failure.getMessage());
                assertFalse(failure.getMessage().contains(base.toString()), failure.getMessage());
            });
        }
    }

    private String existingResult() {
        try {
            return Files.writeString(base.resolve("existing-result.json"), "earlier").toString();
        } catch (IOException error) {
            throw new IllegalStateException(error);
        }
    }

    @Test
    void theRequestAndTheOperatorFilesMayNotLieInsideALedgerDirectory() throws IOException {
        Path inside = Files.writeString(base.resolve("ingestion").resolve("request.json"), "{}");
        runner().withPropertyValues(with("ZOOP_GRAPH_HANDOFF_IMPORT_REQUEST", inside.toString())).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.graph-handoff-import.request "), failure.getMessage());
        });
        Path decisions = Files.writeString(base.resolve("handoff").resolve("decisions.json"), "{}");
        runner().withPropertyValues(with("ZOOP_HANDOFF_DECISIONS", decisions.toString())).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.graph-handoff-import.canonical "), failure.getMessage());
        });
    }

    /** The HTTP source: the seven CLI-only settings left out, the read-only handoff client configured. */
    private String[] httpValues(String... extra) {
        Map<String, String> changed = new LinkedHashMap<>(valid);
        for (String cliOnly : List.of("ZOOP_HANDOFF_CLI", "ZOOP_HANDOFF_STATE_DIR", "ZOOP_RELATION_STATE_DIR",
                "ZOOP_EXTRACTION_STATE_DIR", "ZOOP_HANDOFF_CANONICAL", "ZOOP_HANDOFF_DECISIONS", "ZOOP_HANDOFF_BINDINGS")) {
            changed.remove(cliOnly);
        }
        changed.put("ZOOP_GRAPH_HANDOFF_IMPORT_HANDOFF_SOURCE", "http");
        changed.put("ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED", "true");
        changed.put("ZOOP_AI_HANDOFF_READ_CLIENT_BASE_URL", "https://ai.internal.example");
        changed.put("ZOOP_AI_HANDOFF_READ_CLIENT_TOKEN", "read-token-0123456789abcdefghijklmnopqrstuvwxyz");
        for (int i = 0; i + 1 < extra.length; i += 2) {
            changed.put(extra[i], extra[i + 1]);
        }
        return changed.entrySet().stream().map(entry -> entry.getKey() + "=" + entry.getValue()).toArray(String[]::new);
    }

    @Test
    void theHttpSourceNeedsOnlyTheS2CliAndTheReadClientAndLeavesTheCliOnlySettingsNull() {
        runner().withUserConfiguration(AiHandoffReadClientConfiguration.class).withPropertyValues(httpValues()).run(context -> {
            assertNull(context.getStartupFailure());
            assertNotNull(context.getBean(GraphHandoffRunner.class));
            GraphHandoffImportSettings settings = context.getBean(GraphHandoffImportSettings.class);
            assertEquals(GraphHandoffImportSettings.HandoffSourceKind.HTTP, settings.handoffSource());
            assertNull(settings.handoffCli());
            assertNull(settings.handoffState());
            assertNull(settings.canonical());
            assertEquals(base.resolve("ingestion"), settings.ingestionState());
            assertEquals("GraphHandoffImportProperties[enabled=true, handoffSource=http]",
                    context.getBean(GraphHandoffImportProperties.class).toString());
        });
    }

    @Test
    void aBlankHandoffSourceIsTheCliDefaultAndTheCliRefusesAnIdleReadClient() {
        runner().withPropertyValues(with("ZOOP_GRAPH_HANDOFF_IMPORT_HANDOFF_SOURCE", "")).run(context -> {
            assertNull(context.getStartupFailure());
            assertEquals(GraphHandoffImportSettings.HandoffSourceKind.CLI,
                    context.getBean(GraphHandoffImportSettings.class).handoffSource());
        });
        Map<String, String> cliWithReader = new LinkedHashMap<>(valid);
        cliWithReader.put("ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED", "true");
        cliWithReader.put("ZOOP_AI_HANDOFF_READ_CLIENT_BASE_URL", "https://ai.internal.example");
        cliWithReader.put("ZOOP_AI_HANDOFF_READ_CLIENT_TOKEN", "read-token-0123456789abcdefghijklmnopqrstuvwxyz");
        runner().withUserConfiguration(AiHandoffReadClientConfiguration.class)
                .withPropertyValues(cliWithReader.entrySet().stream().map(entry -> entry.getKey() + "=" + entry.getValue())
                        .toArray(String[]::new))
                .run(context -> {
                    Throwable failure = configurationFailure(context.getStartupFailure());
                    assertNotNull(failure);
                    assertTrue(failure.getMessage().startsWith("zoop.graph-handoff-import.handoff-source "), failure.getMessage());
                    assertTrue(failure.getMessage().contains("zoop.ai.handoff-read-client.enabled"), failure.getMessage());
                });
    }

    @Test
    void theHttpSourceWithoutTheReadClientOrWithACliOnlySettingOrAnUnknownSourceFailsClosed() {
        runner().withPropertyValues(httpValues("ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED", "false")).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.graph-handoff-import.handoff-source "), failure.getMessage());
            assertTrue(failure.getMessage().contains("zoop.ai.handoff-read-client.enabled"), failure.getMessage());
        });
        runner().withUserConfiguration(AiHandoffReadClientConfiguration.class)
                .withPropertyValues(httpValues("ZOOP_HANDOFF_DECISIONS", valid.get("ZOOP_HANDOFF_DECISIONS"))).run(context -> {
                    Throwable failure = configurationFailure(context.getStartupFailure());
                    assertNotNull(failure);
                    assertTrue(failure.getMessage().startsWith("zoop.graph-handoff-import.decisions "), failure.getMessage());
                    assertFalse(failure.getMessage().contains(base.toString()), failure.getMessage());
                });
        runner().withPropertyValues(with("ZOOP_GRAPH_HANDOFF_IMPORT_HANDOFF_SOURCE", "grpc")).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.graph-handoff-import.handoff-source "), failure.getMessage());
        });
    }

    @Test
    void enabledInAWebApplicationContextFailsStartupBeforeAnyServerCouldListen() {
        webRunner().withPropertyValues(values()).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.graph-handoff-import.enabled "), failure.getMessage());
            assertTrue(failure.getMessage().contains("spring.main.web-application-type=none"), failure.getMessage());
        });
    }

    @Test
    void itRefusesToRunBesideAnyOtherArtifactWriterOrTheFixtureSeederThatActivates() {
        String[][] conflicts = {
                {"ZOOP_DOCUMENT_IMPORT_ENABLED=true", "zoop.document-import.enabled"},
                {"ZOOP_DOCUMENT_ANALYSIS_ENABLED=true", "zoop.document-analysis.enabled"},
                {"ZOOP_GRAPH_SNAPSHOT_SOURCE=fixture", "zoop.graph.snapshot.source=fixture"}};
        for (String[] conflict : conflicts) {
            runner().withPropertyValues(values()).withPropertyValues(conflict[0]).run(context -> {
                Throwable failure = configurationFailure(context.getStartupFailure());
                assertNotNull(failure, conflict[0]);
                assertTrue(failure.getMessage().startsWith("zoop.graph-handoff-import.enabled "), failure.getMessage());
                assertTrue(failure.getMessage().contains(conflict[1]), failure.getMessage());
            });
        }
    }
}
