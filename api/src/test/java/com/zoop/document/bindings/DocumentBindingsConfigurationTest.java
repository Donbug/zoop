package com.zoop.document.bindings;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.test.context.ConfigDataApplicationContextInitializer;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The real configuration class in a minimal context (no DB connection, no web server, no component scan). Settings are supplied
 * under their documented {@code ZOOP_*} names and read through the real {@code application.yml}; the shell environment and JVM
 * system properties are removed so only the synthetic values below can reach it.
 */
class DocumentBindingsConfigurationTest {
    @TempDir
    Path temp;
    private Path base;
    private String[] valid;

    @BeforeEach
    void setUp() throws IOException {
        base = temp.toRealPath();
        valid = new String[] {
                "ZOOP_DOCUMENT_BINDINGS_ENABLED=true",
                "ZOOP_DOCUMENT_BINDINGS_OUTPUT=" + base.resolve("bindings.json"),
                "ZOOP_DOCUMENT_BINDINGS_RESULT=" + base.resolve("result.json")};
    }

    private static void isolate(ConfigurableApplicationContext context) {
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
    }

    /** A template over a data source that connects to nothing; the configuration only wires it, it never queries at startup. */
    private static NamedParameterJdbcTemplate jdbc() {
        return new NamedParameterJdbcTemplate(new DriverManagerDataSource("jdbc:postgresql://127.0.0.1:1/unreachable"));
    }

    private ApplicationContextRunner runner() {
        return new ApplicationContextRunner()
                .withInitializer(DocumentBindingsConfigurationTest::isolate)
                .withInitializer(new ConfigDataApplicationContextInitializer())
                .withBean(NamedParameterJdbcTemplate.class, DocumentBindingsConfigurationTest::jdbc)
                .withUserConfiguration(DocumentBindingsConfiguration.class);
    }

    private WebApplicationContextRunner webRunner() {
        return new WebApplicationContextRunner()
                .withInitializer(DocumentBindingsConfigurationTest::isolate)
                .withInitializer(new ConfigDataApplicationContextInitializer())
                .withBean(NamedParameterJdbcTemplate.class, DocumentBindingsConfigurationTest::jdbc)
                .withUserConfiguration(DocumentBindingsConfiguration.class);
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
            if (cause instanceof DocumentBindingsConfigurationException) {
                return cause;
            }
        }
        return null;
    }

    @Test
    void unconfiguredStartsWithoutAnyExportSettingAndWithoutABean() {
        runner().run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(DocumentBindingsRunner.class).isEmpty());
            assertTrue(context.getBeansOfType(DocumentBindingsSettings.class).isEmpty());
            assertTrue(context.getBeansOfType(DocumentBindingsRepository.class).isEmpty());
        });
    }

    @Test
    void disabledIgnoresEverythingElse() {
        runner().withPropertyValues("ZOOP_DOCUMENT_BINDINGS_ENABLED=false", "ZOOP_DOCUMENT_BINDINGS_OUTPUT=relative",
                "ZOOP_DOCUMENT_BINDINGS_SCOPE=everything").run(context -> {
                    assertNull(context.getStartupFailure());
                    assertTrue(context.getBeansOfType(DocumentBindingsRunner.class).isEmpty());
                });
    }

    @Test
    void inheritedEnvironmentAndSystemPropertiesCannotActivateTheExport() {
        String before = System.getProperty("zoop.document-bindings.enabled");
        System.setProperty("zoop.document-bindings.enabled", "true");
        System.setProperty("ZOOP_DOCUMENT_BINDINGS_ENABLED", "true");
        try {
            runner().run(context -> {
                assertNull(context.getStartupFailure());
                assertTrue(context.getBeansOfType(DocumentBindingsRunner.class).isEmpty());
                assertFalse(context.getEnvironment().getPropertySources()
                        .contains(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME));
            });
        } finally {
            if (before == null) {
                System.clearProperty("zoop.document-bindings.enabled");
            } else {
                System.setProperty("zoop.document-bindings.enabled", before);
            }
            System.clearProperty("ZOOP_DOCUMENT_BINDINGS_ENABLED");
        }
    }

    @Test
    void enabledWithValidSettingsInANonWebContextCreatesTheOperatorRunner() {
        runner().withPropertyValues(valid).run(context -> {
            assertNull(context.getStartupFailure());
            assertNotNull(context.getBean(DocumentBindingsRunner.class));
            assertTrue(context.getBean(DocumentBindingsRepository.class) instanceof JdbcDocumentBindingsRepository);
            DocumentBindingsSettings settings = context.getBean(DocumentBindingsSettings.class);
            assertEquals(base.resolve("bindings.json"), settings.output());
            assertEquals(base.resolve("result.json"), settings.result());
            assertNull(settings.selection());
            assertEquals(DocumentBindingsScope.AVAILABLE, settings.scope());
            assertEquals("DocumentBindingsProperties[enabled=true]",
                    context.getBean(DocumentBindingsProperties.class).toString());
        });
    }

    @Test
    void theSelectionAndTheScopeAreReadWhenGiven() throws IOException {
        Path selection = Files.writeString(base.resolve("selection.json"), "{}");
        runner().withPropertyValues(valid).withPropertyValues("ZOOP_DOCUMENT_BINDINGS_SELECTION=" + selection,
                "ZOOP_DOCUMENT_BINDINGS_SCOPE=all").run(context -> {
                    assertNull(context.getStartupFailure());
                    DocumentBindingsSettings settings = context.getBean(DocumentBindingsSettings.class);
                    assertEquals(selection, settings.selection());
                    assertEquals(DocumentBindingsScope.ALL, settings.scope());
                });
    }

    @Test
    void enabledFailsStartupClosedForABadSettingNamingTheSettingNotItsValue() throws IOException {
        String existing = Files.writeString(base.resolve("existing.json"), "earlier").toString();
        String[][] bad = {
                {"ZOOP_DOCUMENT_BINDINGS_OUTPUT", "", "output"},
                {"ZOOP_DOCUMENT_BINDINGS_OUTPUT", "relative/bindings.json", "output"},
                {"ZOOP_DOCUMENT_BINDINGS_OUTPUT", existing, "output"},
                {"ZOOP_DOCUMENT_BINDINGS_OUTPUT", base.resolve("missing-dir").resolve("bindings.json").toString(), "output"},
                {"ZOOP_DOCUMENT_BINDINGS_RESULT", "", "result"},
                {"ZOOP_DOCUMENT_BINDINGS_RESULT", existing, "result"},
                {"ZOOP_DOCUMENT_BINDINGS_RESULT", base.resolve("bindings.json").toString(), "result"}};
        for (String[] entry : bad) {
            runner().withPropertyValues(with(entry[0], entry[1])).run(context -> {
                Throwable failure = configurationFailure(context.getStartupFailure());
                assertNotNull(failure, entry[0] + "=" + entry[1]);
                assertTrue(failure.getMessage().startsWith("zoop.document-bindings." + entry[2] + " "), failure.getMessage());
                assertFalse(failure.getMessage().contains(base.toString()), failure.getMessage());
            });
        }
        runner().withPropertyValues(valid).withPropertyValues("ZOOP_DOCUMENT_BINDINGS_SELECTION=" + base.resolve("missing.json"))
                .run(context -> {
                    Throwable failure = configurationFailure(context.getStartupFailure());
                    assertNotNull(failure);
                    assertTrue(failure.getMessage().startsWith("zoop.document-bindings.selection "), failure.getMessage());
                });
        runner().withPropertyValues(valid).withPropertyValues("ZOOP_DOCUMENT_BINDINGS_SCOPE=everything").run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.document-bindings.scope "), failure.getMessage());
        });
    }

    @Test
    void enabledInAWebApplicationContextFailsStartupBeforeAnyServerCouldListen() {
        webRunner().withPropertyValues(valid).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.document-bindings.enabled "), failure.getMessage());
            assertTrue(failure.getMessage().contains("spring.main.web-application-type=none"), failure.getMessage());
        });
    }

    @Test
    void enabledNextToAnotherOperatorCommandFailsStartupSoTheExitCodeIsThisRunsAlone() {
        for (String other : DocumentBindingsConfiguration.OTHER_OPERATOR_COMMANDS) {
            runner().withPropertyValues(valid).withPropertyValues(other + "=true").run(context -> {
                Throwable failure = configurationFailure(context.getStartupFailure());
                assertNotNull(failure, other);
                assertTrue(failure.getMessage().startsWith("zoop.document-bindings.enabled "), failure.getMessage());
                assertTrue(failure.getMessage().contains(other), failure.getMessage());
            });
        }
    }

    @Test
    void aWebContextWithTheExportDisabledStartsAsBefore() {
        webRunner().run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(DocumentBindingsRunner.class).isEmpty());
        });
    }
}
