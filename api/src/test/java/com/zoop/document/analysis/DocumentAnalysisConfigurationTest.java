package com.zoop.document.analysis;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Clock;

import com.zoop.ai.AiAnalysisClient;
import com.zoop.ai.AnalysisAcknowledgement;
import com.zoop.ai.AnalysisJobStatus;
import com.zoop.ai.AnalysisResult;
import com.zoop.ai.AnalysisSubmission;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.analysis.repository.DocumentAnalysisRepository;
import com.zoop.document.analysis.service.DocumentAnalysisService;
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
class DocumentAnalysisConfigurationTest {
    @TempDir
    Path temp;
    private Path base;
    private String[] valid;

    /** The analysis needs a client but never calls one in a configuration test. */
    private static final class NoClient implements AiAnalysisClient {
        @Override
        public AnalysisAcknowledgement submit(AnalysisSubmission submission) {
            throw new UnsupportedOperationException();
        }

        @Override
        public AnalysisJobStatus status(String jobId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public AnalysisResult result(String jobId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public AnalysisJobStatus cancel(String jobId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public AnalysisAcknowledgement recover(String jobId) {
            throw new UnsupportedOperationException();
        }
    }

    @BeforeEach
    void setUp() throws IOException {
        base = temp.toRealPath();
        Path cli = Files.writeString(base.resolve("zoop-ai-ingest"), "#!/bin/sh\n");
        Files.setPosixFilePermissions(cli, PosixFilePermissions.fromString("rwx------"));
        valid = new String[] {
                "ZOOP_DOCUMENT_ANALYSIS_ENABLED=true",
                "ZOOP_DOCUMENT_ANALYSIS_REQUEST=" + Files.writeString(base.resolve("request.json"), "{}"),
                "ZOOP_DOCUMENT_ANALYSIS_RESULT=" + base.resolve("result.json"),
                "ZOOP_DOCUMENT_ANALYSIS_GRANTS=" + Files.writeString(base.resolve("grants.json"), "{}"),
                "ZOOP_INGESTION_CLI=" + cli,
                "ZOOP_INGESTION_STATE_DIR=" + Files.createDirectory(base.resolve("state")),
                "ZOOP_INGESTION_SOURCES=" + Files.writeString(base.resolve("sources.json"), "{}"),
                "ZOOP_ARTIFACT_ROOT=" + Files.createDirectory(base.resolve("artifacts"))};
    }

    private static void isolate(ConfigurableApplicationContext context) {
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
    }

    private static InMemoryAnalysisWorld analyses() {
        return new InMemoryAnalysisWorld();
    }

    private ApplicationContextRunner runner(boolean withClient) {
        ApplicationContextRunner runner = new ApplicationContextRunner()
                .withInitializer(DocumentAnalysisConfigurationTest::isolate)
                .withInitializer(new ConfigDataApplicationContextInitializer())
                .withBean(Clock.class, Clock::systemUTC)
                .withBean(DocumentRegistryRepository.class, InMemoryDocumentRegistry::new)
                .withBean(DocumentAnalysisRepository.class, DocumentAnalysisConfigurationTest::analyses)
                .withBean(DocumentAnalysisService.class, () -> new DocumentAnalysisService(new InMemoryDocumentRegistry(), analyses(),
                        Clock.systemUTC()))
                .withUserConfiguration(DocumentAnalysisConfiguration.class);
        return withClient ? runner.withBean(AiAnalysisClient.class, NoClient::new) : runner;
    }

    private WebApplicationContextRunner webRunner() {
        return new WebApplicationContextRunner()
                .withInitializer(DocumentAnalysisConfigurationTest::isolate)
                .withInitializer(new ConfigDataApplicationContextInitializer())
                .withBean(Clock.class, Clock::systemUTC)
                .withBean(DocumentRegistryRepository.class, InMemoryDocumentRegistry::new)
                .withBean(DocumentAnalysisRepository.class, DocumentAnalysisConfigurationTest::analyses)
                .withBean(DocumentAnalysisService.class, () -> new DocumentAnalysisService(new InMemoryDocumentRegistry(), analyses(),
                        Clock.systemUTC()))
                .withBean(AiAnalysisClient.class, NoClient::new)
                .withUserConfiguration(DocumentAnalysisConfiguration.class);
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
            if (cause instanceof DocumentAnalysisConfigurationException) {
                return cause;
            }
        }
        return null;
    }

    @Test
    void unconfiguredStartsWithoutAnyAnalysisSettingAndWithoutABean() {
        runner(false).run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(DocumentAnalysisRunner.class).isEmpty());
            assertTrue(context.getBeansOfType(DocumentAnalysisSettings.class).isEmpty());
            assertTrue(context.getBeansOfType(ArtifactFileStore.class).isEmpty());
        });
    }

    @Test
    void disabledIgnoresEverythingElse() {
        runner(false).withPropertyValues("ZOOP_DOCUMENT_ANALYSIS_ENABLED=false", "ZOOP_DOCUMENT_ANALYSIS_REQUEST=relative",
                "ZOOP_ARTIFACT_ROOT=not/absolute").run(context -> {
                    assertNull(context.getStartupFailure());
                    assertTrue(context.getBeansOfType(DocumentAnalysisRunner.class).isEmpty());
                });
    }

    @Test
    void inheritedEnvironmentAndSystemPropertiesCannotActivateTheAnalysis() {
        String before = System.getProperty("zoop.document-analysis.enabled");
        System.setProperty("zoop.document-analysis.enabled", "true");
        System.setProperty("ZOOP_DOCUMENT_ANALYSIS_ENABLED", "true");
        try {
            runner(true).run(context -> {
                assertNull(context.getStartupFailure());
                assertTrue(context.getBeansOfType(DocumentAnalysisRunner.class).isEmpty());
                assertFalse(context.getEnvironment().getPropertySources()
                        .contains(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME));
            });
        } finally {
            if (before == null) {
                System.clearProperty("zoop.document-analysis.enabled");
            } else {
                System.setProperty("zoop.document-analysis.enabled", before);
            }
            System.clearProperty("ZOOP_DOCUMENT_ANALYSIS_ENABLED");
        }
    }

    @Test
    void enabledWithValidSettingsAndAnAiClientInANonWebContextCreatesTheOperatorRunner() {
        runner(true).withPropertyValues(valid).run(context -> {
            assertNull(context.getStartupFailure());
            assertNotNull(context.getBean(DocumentAnalysisRunner.class));
            assertNotNull(context.getBean(ArtifactFileStore.class));
            DocumentAnalysisSettings settings = context.getBean(DocumentAnalysisSettings.class);
            assertEquals(base.resolve("result.json"), settings.result());
            assertEquals(base.resolve("grants.json"), settings.grants());
            assertEquals(base.resolve("artifacts"), settings.artifactRoot());
            assertEquals("DocumentAnalysisProperties[enabled=true]", context.getBean(DocumentAnalysisProperties.class).toString());
        });
    }

    @Test
    void enabledWithoutTheAiClientFailsStartupClosed() {
        runner(false).withPropertyValues(valid).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.document-analysis.enabled "), failure.getMessage());
            assertTrue(failure.getMessage().contains("zoop.ai.client.enabled=true"), failure.getMessage());
        });
    }

    @Test
    void enabledFailsStartupClosedForABadSettingNamingTheSettingNotItsValue() throws IOException {
        Files.writeString(base.resolve("state").resolve("inside.json"), "{}");
        String[][] bad = {
                {"ZOOP_DOCUMENT_ANALYSIS_REQUEST", "", "request"},
                {"ZOOP_DOCUMENT_ANALYSIS_REQUEST", "relative/request.json", "request"},
                {"ZOOP_DOCUMENT_ANALYSIS_REQUEST", "MISSING", "request"},
                {"ZOOP_DOCUMENT_ANALYSIS_RESULT", "", "result"},
                {"ZOOP_DOCUMENT_ANALYSIS_RESULT", "EXISTING", "result"},
                {"ZOOP_DOCUMENT_ANALYSIS_GRANTS", "", "grants"},
                {"ZOOP_DOCUMENT_ANALYSIS_GRANTS", "MISSING", "grants"},
                {"ZOOP_DOCUMENT_ANALYSIS_GRANTS", "INSIDE_STATE", "grants"},
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
                case "INSIDE_STATE" -> base.resolve("state").resolve("inside.json").toString();
                default -> entry[1];
            };
            runner(true).withPropertyValues(with(entry[0], value)).run(context -> {
                Throwable failure = configurationFailure(context.getStartupFailure());
                assertNotNull(failure, entry[0] + "=" + entry[1]);
                assertTrue(failure.getMessage().startsWith("zoop.document-analysis." + entry[2] + " "), failure.getMessage());
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
            assertTrue(failure.getMessage().startsWith("zoop.document-analysis.enabled "), failure.getMessage());
            assertTrue(failure.getMessage().contains("spring.main.web-application-type=none"), failure.getMessage());
        });
    }

    @Test
    void enabledNextToTheDocumentImportFailsStartupBecauseBothHoldTheStoreLock() {
        runner(true).withPropertyValues(valid).withPropertyValues("ZOOP_DOCUMENT_IMPORT_ENABLED=true").run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.document-analysis.enabled "), failure.getMessage());
            assertTrue(failure.getMessage().contains("zoop.document-import.enabled"), failure.getMessage());
        });
    }

    @Test
    void aWebContextWithTheAnalysisDisabledStartsAsBefore() {
        webRunner().run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(DocumentAnalysisRunner.class).isEmpty());
        });
    }
}
