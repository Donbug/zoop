package com.zoop.ai.config;

import com.zoop.ai.AiAnalysisClient;
import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.http.HttpAiAnalysisClient;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.ConfigDataApplicationContextInitializer;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.core.env.StandardEnvironment;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The real configuration class in a minimal context (no DB, no web server, no component scan of the application).
 * Environment names are the documented ones: properties are supplied under their {@code ZOOP_AI_CLIENT_*} names and read
 * through the real {@code application.yml}.
 */
class AiClientConfigurationTest {
    private static final String TOKEN = "config-token-0123456789abcdefghijklmnopqrstuvwx";

    /**
     * The runner starts from a standard environment, which includes the developer's real shell environment and JVM system
     * properties. Both sources are removed so only the synthetic values below can reach the real {@code application.yml}
     * placeholders; a shell already configured with real ZOOP_AI_CLIENT_* values cannot change these tests.
     */
    private final ApplicationContextRunner runner = new ApplicationContextRunner()
            .withInitializer(context -> {
                context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
                context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
            })
            .withInitializer(new ConfigDataApplicationContextInitializer())
            .withUserConfiguration(AiClientConfiguration.class);

    @Test
    void inheritedEnvironmentAndSystemPropertiesCannotActivateTheClient() {
        String[] names = {"ZOOP_AI_CLIENT_ENABLED", "ZOOP_AI_CLIENT_BASE_URL", "ZOOP_AI_CLIENT_TOKEN", "zoop.ai.client.enabled"};
        String[] before = new String[names.length];
        for (int i = 0; i < names.length; i++) {
            before[i] = System.getProperty(names[i]);
        }
        System.setProperty("ZOOP_AI_CLIENT_ENABLED", "true");
        System.setProperty("zoop.ai.client.enabled", "true");
        System.setProperty("ZOOP_AI_CLIENT_BASE_URL", "http://127.0.0.1:1");
        System.setProperty("ZOOP_AI_CLIENT_TOKEN", TOKEN);
        try {
            runner.run(context -> {
                assertTrue(context.getStartupFailure() == null);
                assertTrue(context.getBeansOfType(AiAnalysisClient.class).isEmpty());
                assertFalse(context.getEnvironment().getPropertySources()
                        .contains(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME));
                assertFalse(context.getEnvironment().getPropertySources()
                        .contains(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME));
            });
        } finally {
            for (int i = 0; i < names.length; i++) {
                if (before[i] == null) {
                    System.clearProperty(names[i]);
                } else {
                    System.setProperty(names[i], before[i]);
                }
            }
        }
    }

    @Test
    void unconfiguredStartsWithoutAnyAiSettingAndWithoutABean() {
        runner.run(context -> {
            assertTrue(context.getStartupFailure() == null);
            assertTrue(context.getBeansOfType(AiAnalysisClient.class).isEmpty());
        });
    }

    @Test
    void disabledIgnoresEverythingElse() {
        runner.withPropertyValues("ZOOP_AI_CLIENT_ENABLED=false", "ZOOP_AI_CLIENT_BASE_URL=not a url", "ZOOP_AI_CLIENT_TOKEN=x")
                .run(context -> {
                    assertTrue(context.getStartupFailure() == null);
                    assertTrue(context.getBeansOfType(AiAnalysisClient.class).isEmpty());
                });
    }

    @Test
    void enabledWithValidSettingsCreatesTheProductionClient() {
        runner.withPropertyValues("ZOOP_AI_CLIENT_ENABLED=true", "ZOOP_AI_CLIENT_BASE_URL=http://127.0.0.1:8797",
                        "ZOOP_AI_CLIENT_TOKEN=" + TOKEN, "ZOOP_AI_CLIENT_CONNECT_TIMEOUT=1s", "ZOOP_AI_CLIENT_REQUEST_TIMEOUT=5s",
                        "ZOOP_AI_CLIENT_MAX_RESPONSE_BYTES=131072")
                .run(context -> {
                    assertTrue(context.getStartupFailure() == null);
                    assertInstanceOf(HttpAiAnalysisClient.class, context.getBean(AiAnalysisClient.class));
                    AiClientProperties properties = context.getBean(AiClientProperties.class);
                    assertEquals(131_072, properties.maxResponseBytes());
                    assertFalse(properties.toString().contains(TOKEN));
                });
    }

    @Test
    void enabledFailsStartupClosedForEveryBadSettingWithoutPrintingValues() {
        String[][] bad = {
                {"ZOOP_AI_CLIENT_BASE_URL=", "ZOOP_AI_CLIENT_TOKEN=" + TOKEN},
                {"ZOOP_AI_CLIENT_BASE_URL=http://ai.internal.example", "ZOOP_AI_CLIENT_TOKEN=" + TOKEN},
                {"ZOOP_AI_CLIENT_BASE_URL=https://ai.internal.example", "ZOOP_AI_CLIENT_TOKEN="},
                {"ZOOP_AI_CLIENT_BASE_URL=https://ai.internal.example", "ZOOP_AI_CLIENT_TOKEN=too-short"},
                {"ZOOP_AI_CLIENT_BASE_URL=https://ai.internal.example", "ZOOP_AI_CLIENT_TOKEN=" + TOKEN,
                        "ZOOP_AI_CLIENT_REQUEST_TIMEOUT=0s"},
                {"ZOOP_AI_CLIENT_BASE_URL=https://ai.internal.example", "ZOOP_AI_CLIENT_TOKEN=" + TOKEN,
                        "ZOOP_AI_CLIENT_CONNECT_TIMEOUT=10m"},
        };
        for (String[] values : bad) {
            String[] all = new String[values.length + 1];
            all[0] = "ZOOP_AI_CLIENT_ENABLED=true";
            System.arraycopy(values, 0, all, 1, values.length);
            runner.withPropertyValues(all).run(context -> {
                Throwable failure = context.getStartupFailure();
                assertTrue(failure != null, String.join(" ", values));
                boolean named = false;
                for (Throwable t = failure; t != null; t = t.getCause()) {
                    named |= t instanceof AiClientConfigurationException;
                    assertFalse(String.valueOf(t.getMessage()).contains(TOKEN), "startup failure leaked the token");
                }
                assertTrue(named, "expected the failure to be an AiClientConfigurationException");
            });
        }
    }
}
