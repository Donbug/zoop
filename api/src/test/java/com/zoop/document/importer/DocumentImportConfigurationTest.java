package com.zoop.document.importer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Clock;
import java.util.ArrayList;
import java.util.List;

import com.zoop.ai.config.AiObservationExportClientConfiguration;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.service.DocumentRegistrationService;
import com.zoop.document.service.InMemoryDocumentRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.test.context.ConfigDataApplicationContextInitializer;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.StandardEnvironment;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The real configuration class in a minimal context (no DB, no web server, no component scan). Settings are supplied under
 * their documented {@code ZOOP_*} names and read through the real {@code application.yml}; the shell environment and JVM
 * system properties are removed so only the synthetic values below can reach it.
 */
class DocumentImportConfigurationTest {
    @TempDir
    Path temp;
    private Path base;
    private String[] valid;

    @BeforeEach
    void setUp() throws IOException {
        base = temp.toRealPath();
        Path cli = Files.writeString(base.resolve("zoop-ai-ingest"), "#!/bin/sh\n");
        Files.setPosixFilePermissions(cli, PosixFilePermissions.fromString("rwx------"));
        valid = new String[] {
                "ZOOP_DOCUMENT_IMPORT_ENABLED=true",
                "ZOOP_DOCUMENT_IMPORT_REQUEST=" + Files.writeString(base.resolve("request.json"), "{}"),
                "ZOOP_DOCUMENT_IMPORT_RESULT=" + base.resolve("result.json"),
                "ZOOP_INGESTION_CLI=" + cli,
                "ZOOP_INGESTION_STATE_DIR=" + Files.createDirectory(base.resolve("state")),
                "ZOOP_INGESTION_SOURCES=" + Files.writeString(base.resolve("sources.json"), "{}"),
                "ZOOP_ARTIFACT_ROOT=" + Files.createDirectory(base.resolve("artifacts"))};
    }

    private static void isolate(ConfigurableApplicationContext context) {
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
    }

    private static DocumentRegistrationService registration() {
        return new DocumentRegistrationService(new InMemoryDocumentRegistry(), Clock.systemUTC());
    }

    private ApplicationContextRunner runner() {
        return new ApplicationContextRunner()
                .withInitializer(DocumentImportConfigurationTest::isolate)
                .withInitializer(new ConfigDataApplicationContextInitializer())
                .withBean(DocumentRegistrationService.class, DocumentImportConfigurationTest::registration)
                .withUserConfiguration(DocumentImportConfiguration.class);
    }

    private WebApplicationContextRunner webRunner() {
        return new WebApplicationContextRunner()
                .withInitializer(DocumentImportConfigurationTest::isolate)
                .withInitializer(new ConfigDataApplicationContextInitializer())
                .withBean(DocumentRegistrationService.class, DocumentImportConfigurationTest::registration)
                .withUserConfiguration(DocumentImportConfiguration.class);
    }

    private String[] with(String name, String value) {
        String[] values = valid.clone();
        for (int index = 0; index < values.length; index++) {
            if (values[index].startsWith(name + "=")) {
                values[index] = name + "=" + value;
            }
        }
        return values;
    }

    private static Throwable configurationFailure(Throwable failure) {
        for (Throwable cause = failure; cause != null; cause = cause.getCause()) {
            if (cause instanceof DocumentImportConfigurationException) {
                return cause;
            }
        }
        return null;
    }

    @Test
    void unconfiguredStartsWithoutAnyImportSettingAndWithoutABean() {
        runner().run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(DocumentImportRunner.class).isEmpty());
            assertTrue(context.getBeansOfType(DocumentImportSettings.class).isEmpty());
            assertTrue(context.getBeansOfType(ArtifactFileStore.class).isEmpty());
        });
    }

    @Test
    void disabledIgnoresEverythingElse() {
        runner().withPropertyValues("ZOOP_DOCUMENT_IMPORT_ENABLED=false", "ZOOP_DOCUMENT_IMPORT_REQUEST=relative",
                "ZOOP_ARTIFACT_ROOT=not/absolute").run(context -> {
                    assertNull(context.getStartupFailure());
                    assertTrue(context.getBeansOfType(DocumentImportRunner.class).isEmpty());
                });
    }

    @Test
    void inheritedEnvironmentAndSystemPropertiesCannotActivateTheImport() {
        String before = System.getProperty("zoop.document-import.enabled");
        System.setProperty("zoop.document-import.enabled", "true");
        System.setProperty("ZOOP_DOCUMENT_IMPORT_ENABLED", "true");
        try {
            runner().run(context -> {
                assertNull(context.getStartupFailure());
                assertTrue(context.getBeansOfType(DocumentImportRunner.class).isEmpty());
                assertFalse(context.getEnvironment().getPropertySources()
                        .contains(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME));
            });
        } finally {
            if (before == null) {
                System.clearProperty("zoop.document-import.enabled");
            } else {
                System.setProperty("zoop.document-import.enabled", before);
            }
            System.clearProperty("ZOOP_DOCUMENT_IMPORT_ENABLED");
        }
    }

    @Test
    void enabledWithValidSettingsInANonWebContextCreatesTheOperatorRunner() {
        runner().withPropertyValues(valid).run(context -> {
            assertNull(context.getStartupFailure());
            assertNotNull(context.getBean(DocumentImportRunner.class));
            assertNotNull(context.getBean(ArtifactFileStore.class));
            DocumentImportSettings settings = context.getBean(DocumentImportSettings.class);
            assertEquals(base.resolve("result.json"), settings.result());
            assertEquals(base.resolve("artifacts"), settings.artifactRoot());
            assertEquals("DocumentImportProperties[enabled=true, observationSource=cli]",
                    context.getBean(DocumentImportProperties.class).toString());
            assertEquals(ObservationSource.CLI, settings.observationSource());
        });
    }

    /** The HTTP observation source: the three S2-1 CLI settings left out, the observation export client configured. */
    private String[] observationHttp() {
        List<String> values = new ArrayList<>();
        for (String value : valid) {
            if (!value.startsWith("ZOOP_INGESTION_")) values.add(value);
        }
        values.add("ZOOP_DOCUMENT_IMPORT_OBSERVATION_SOURCE=http");
        values.add("ZOOP_AI_OBSERVATION_EXPORT_CLIENT_ENABLED=true");
        values.add("ZOOP_AI_OBSERVATION_EXPORT_CLIENT_BASE_URL=https://ai.internal.example");
        values.add("ZOOP_AI_OBSERVATION_EXPORT_CLIENT_TOKEN=export-token-0123456789abcdefghijklmnopqrstuvwxyz");
        return values.toArray(String[]::new);
    }

    private static String[] plus(String[] values, String... more) {
        List<String> all = new ArrayList<>(List.of(values));
        all.addAll(List.of(more));
        return all.toArray(String[]::new);
    }

    @Test
    void theHttpObservationSourceNeedsTheExportClientNotTheS2CliAndLeavesTheCliSettingsNull() {
        runner().withUserConfiguration(AiObservationExportClientConfiguration.class).withPropertyValues(observationHttp())
                .run(context -> {
                    assertNull(context.getStartupFailure());
                    assertNotNull(context.getBean(DocumentImportRunner.class));
                    DocumentImportSettings settings = context.getBean(DocumentImportSettings.class);
                    assertEquals(ObservationSource.HTTP, settings.observationSource());
                    assertNull(settings.ingestionCli());
                    assertNull(settings.ingestionState());
                    assertNull(settings.ingestionSources());
                    assertEquals(base.resolve("artifacts"), settings.artifactRoot());
                    assertEquals("DocumentImportProperties[enabled=true, observationSource=http]",
                            context.getBean(DocumentImportProperties.class).toString());
                });
    }

    @Test
    void theHttpSourceWithoutTheClientOrWithACliSettingOrAnUnknownSourceFailsClosedWhileCliIgnoresTheClient() {
        runner().withPropertyValues(plus(observationHttp(), "ZOOP_AI_OBSERVATION_EXPORT_CLIENT_ENABLED=false")).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.document-import.observation-source "), failure.getMessage());
            assertTrue(failure.getMessage().contains("zoop.ai.observation-export-client.enabled"), failure.getMessage());
        });
        runner().withUserConfiguration(AiObservationExportClientConfiguration.class)
                .withPropertyValues(plus(observationHttp(), "ZOOP_INGESTION_CLI=" + base.resolve("zoop-ai-ingest"))).run(context -> {
                    Throwable failure = configurationFailure(context.getStartupFailure());
                    assertNotNull(failure);
                    assertTrue(failure.getMessage().startsWith("zoop.document-import.ingestion-cli "), failure.getMessage());
                    assertTrue(failure.getMessage().contains("observation-source=http"), failure.getMessage());
                    assertFalse(failure.getMessage().contains(base.toString()), failure.getMessage());
                });
        runner().withPropertyValues(plus(valid, "ZOOP_DOCUMENT_IMPORT_OBSERVATION_SOURCE=grpc")).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.document-import.observation-source "), failure.getMessage());
        });
        // The web application sharing this environment may hold the export client: cli does not refuse it.
        runner().withUserConfiguration(AiObservationExportClientConfiguration.class)
                .withPropertyValues(plus(valid, "ZOOP_AI_OBSERVATION_EXPORT_CLIENT_ENABLED=true",
                        "ZOOP_AI_OBSERVATION_EXPORT_CLIENT_BASE_URL=https://ai.internal.example",
                        "ZOOP_AI_OBSERVATION_EXPORT_CLIENT_TOKEN=export-token-0123456789abcdefghijklmnopqrstuvwxyz"))
                .run(context -> {
                    assertNull(context.getStartupFailure());
                    assertEquals(ObservationSource.CLI,
                            context.getBean(DocumentImportSettings.class).observationSource());
                });
    }

    @Test
    void enabledFailsStartupClosedForABadSettingNamingTheSettingNotItsValue() {
        String[][] bad = {
                {"ZOOP_DOCUMENT_IMPORT_REQUEST", "", "request"},
                {"ZOOP_DOCUMENT_IMPORT_REQUEST", "relative/request.json", "request"},
                {"ZOOP_DOCUMENT_IMPORT_REQUEST", "MISSING", "request"},
                {"ZOOP_DOCUMENT_IMPORT_RESULT", "", "result"},
                {"ZOOP_DOCUMENT_IMPORT_RESULT", "EXISTING", "result"},
                {"ZOOP_INGESTION_CLI", "", "ingestion-cli"},
                {"ZOOP_INGESTION_CLI", "MISSING", "ingestion-cli"},
                {"ZOOP_INGESTION_STATE_DIR", "MISSING", "ingestion-state-dir"},
                {"ZOOP_INGESTION_SOURCES", "MISSING", "ingestion-sources"},
                {"ZOOP_ARTIFACT_ROOT", "", "artifact-root"},
                {"ZOOP_ARTIFACT_ROOT", "MISSING", "artifact-root"},
                {"ZOOP_ARTIFACT_ROOT", "STATE", "artifact-root"}};
        for (String[] entry : bad) {
            String value = switch (entry[1]) {
                case "MISSING" -> base.resolve("missing-" + entry[2]).toString();
                case "EXISTING" -> existingResult();
                case "STATE" -> base.resolve("state").toString();
                default -> entry[1];
            };
            runner().withPropertyValues(with(entry[0], value)).run(context -> {
                Throwable failure = configurationFailure(context.getStartupFailure());
                assertNotNull(failure, entry[0] + "=" + entry[1]);
                assertTrue(failure.getMessage().startsWith("zoop.document-import." + entry[2] + " "), failure.getMessage());
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
    void enabledInAWebApplicationContextFailsStartupBeforeAnyServerCouldListen() {
        webRunner().withPropertyValues(valid).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.document-import.enabled "), failure.getMessage());
            assertTrue(failure.getMessage().contains("spring.main.web-application-type=none"), failure.getMessage());
        });
    }

    @Test
    void enabledNextToTheDocumentAnalysisFailsStartupBecauseBothHoldTheStoreLock() {
        runner().withPropertyValues(valid).withPropertyValues("ZOOP_DOCUMENT_ANALYSIS_ENABLED=true").run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.document-import.enabled "), failure.getMessage());
            assertTrue(failure.getMessage().contains("zoop.document-analysis.enabled"), failure.getMessage());
        });
    }

    @Test
    void aWebContextWithTheImportDisabledStartsAsBefore() {
        webRunner().run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(DocumentImportRunner.class).isEmpty());
        });
    }
}
