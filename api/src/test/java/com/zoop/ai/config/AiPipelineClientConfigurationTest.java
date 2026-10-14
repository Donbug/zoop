package com.zoop.ai.config;

import com.zoop.ai.AiAnalysisClient;
import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.extraction.ExtractionClient;
import com.zoop.ai.http.HttpExtractionClient;
import com.zoop.ai.http.HttpRelationClient;
import com.zoop.ai.relation.RelationClient;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.ConfigDataApplicationContextInitializer;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.core.env.StandardEnvironment;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The S2 and S3 client configurations in a minimal context, with the real {@code application.yml} names and without the
 * developer's shell environment or JVM system properties (both property sources are removed, so a shell holding real
 * {@code ZOOP_AI_*} values cannot change the result). Each family is switched on and validated on its own.
 */
class AiPipelineClientConfigurationTest {
    private static final String TOKEN = "pipeline-token-0123456789abcdefghijklmnopqrstu";

    private final ApplicationContextRunner runner = new ApplicationContextRunner()
            .withInitializer(context -> {
                context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
                context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
            })
            .withInitializer(new ConfigDataApplicationContextInitializer())
            .withUserConfiguration(AiClientConfiguration.class, AiExtractionClientConfiguration.class, AiRelationClientConfiguration.class);

    @Test
    void unconfiguredAndInheritedEnvironmentCreateNoClientAndNeedNoSetting() {
        String[] names = {"ZOOP_AI_EXTRACTION_CLIENT_ENABLED", "ZOOP_AI_RELATION_CLIENT_ENABLED", "zoop.ai.extraction-client.enabled",
                "zoop.ai.relation-client.enabled"};
        for (String name : names) {
            System.setProperty(name, "true");
        }
        try {
            runner.run(context -> {
                assertNull(context.getStartupFailure());
                assertTrue(context.getBeansOfType(ExtractionClient.class).isEmpty());
                assertTrue(context.getBeansOfType(RelationClient.class).isEmpty());
                assertTrue(context.getBeansOfType(AiAnalysisClient.class).isEmpty());
            });
        } finally {
            for (String name : names) {
                System.clearProperty(name);
            }
        }
    }

    @Test
    void eachFamilyIsEnabledAloneWithItsOwnTokenAndNeverEnablesAnotherOne() {
        runner.withPropertyValues("ZOOP_AI_EXTRACTION_CLIENT_ENABLED=true", "ZOOP_AI_EXTRACTION_CLIENT_BASE_URL=http://127.0.0.1:8797",
                "ZOOP_AI_EXTRACTION_CLIENT_TOKEN=" + TOKEN, "ZOOP_AI_EXTRACTION_CLIENT_MAX_RESPONSE_BYTES=131072").run(context -> {
            assertNull(context.getStartupFailure());
            assertInstanceOf(HttpExtractionClient.class, context.getBean(ExtractionClient.class));
            assertTrue(context.getBeansOfType(RelationClient.class).isEmpty());
            assertTrue(context.getBeansOfType(AiAnalysisClient.class).isEmpty());
            AiExtractionClientProperties properties = context.getBean(AiExtractionClientProperties.class);
            assertEquals(131_072, properties.maxResponseBytes());
            assertFalse(properties.toString().contains(TOKEN));
        });
        runner.withPropertyValues("ZOOP_AI_RELATION_CLIENT_ENABLED=true", "ZOOP_AI_RELATION_CLIENT_BASE_URL=https://ai.internal.example/ai",
                "ZOOP_AI_RELATION_CLIENT_TOKEN=" + TOKEN, "ZOOP_AI_RELATION_CLIENT_REQUEST_TIMEOUT=5s").run(context -> {
            assertNull(context.getStartupFailure());
            assertInstanceOf(HttpRelationClient.class, context.getBean(RelationClient.class));
            assertTrue(context.getBeansOfType(ExtractionClient.class).isEmpty());
            assertFalse(context.getBean(AiRelationClientProperties.class).toString().contains(TOKEN));
        });
        // the S1 client's own settings do not configure (or leak into) the S2 and S3 clients
        runner.withPropertyValues("ZOOP_AI_CLIENT_ENABLED=true", "ZOOP_AI_CLIENT_BASE_URL=http://127.0.0.1:8797", "ZOOP_AI_CLIENT_TOKEN=" + TOKEN)
                .run(context -> {
                    assertNull(context.getStartupFailure());
                    assertNotNull(context.getBean(AiAnalysisClient.class));
                    assertTrue(context.getBeansOfType(ExtractionClient.class).isEmpty());
                    assertTrue(context.getBeansOfType(RelationClient.class).isEmpty());
                });
    }

    @Test
    void anEnabledFamilyFailsStartupClosedUnderItsOwnPrefixWithoutPrintingValues() {
        String[][] families = {{"EXTRACTION", "zoop.ai.extraction-client."}, {"RELATION", "zoop.ai.relation-client."}};
        for (String[] family : families) {
            String prefix = "ZOOP_AI_" + family[0] + "_CLIENT_";
            String[][] bad = {
                    {prefix + "BASE_URL=http://ai.internal.example", prefix + "TOKEN=" + TOKEN},
                    {prefix + "BASE_URL=https://ai.internal.example", prefix + "TOKEN=too-short"},
                    {prefix + "BASE_URL=https://ai.internal.example", prefix + "TOKEN=" + TOKEN, prefix + "REQUEST_TIMEOUT=0s"},
            };
            for (String[] values : bad) {
                String[] all = new String[values.length + 1];
                all[0] = prefix + "ENABLED=true";
                System.arraycopy(values, 0, all, 1, values.length);
                runner.withPropertyValues(all).run(context -> {
                    Throwable failure = context.getStartupFailure();
                    assertNotNull(failure, String.join(" ", values));
                    AiClientConfigurationException named = null;
                    for (Throwable t = failure; t != null; t = t.getCause()) {
                        assertFalse(String.valueOf(t.getMessage()).contains(TOKEN), "startup failure leaked the token");
                        if (t instanceof AiClientConfigurationException configuration) {
                            named = configuration;
                        }
                    }
                    assertNotNull(named, "expected an AiClientConfigurationException");
                    assertTrue(named.getMessage().startsWith(family[1]), named.getMessage());
                });
            }
        }
    }
}
