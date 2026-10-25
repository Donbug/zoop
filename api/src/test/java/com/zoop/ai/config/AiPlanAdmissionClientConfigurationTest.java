package com.zoop.ai.config;

import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.extraction.ExtractionClient;
import com.zoop.ai.http.HttpPlanAdmissionClient;
import com.zoop.ai.plan.PlanAdmissionClient;
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

class AiPlanAdmissionClientConfigurationTest {
    private static final String TOKEN = "plan-token-0123456789abcdefghijklmnopqrstuvwxyz";
    private final ApplicationContextRunner runner = new ApplicationContextRunner()
            .withInitializer(context -> {
                context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
                context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
            })
            .withInitializer(new ConfigDataApplicationContextInitializer())
            .withUserConfiguration(AiPlanAdmissionClientConfiguration.class, AiExtractionClientConfiguration.class, AiRelationClientConfiguration.class);

    @Test
    void absentConfigurationIsOffAndNeedsNoTokenOrPolicy() {
        runner.run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(PlanAdmissionClient.class).isEmpty());
            assertTrue(context.getBeansOfType(ExtractionClient.class).isEmpty());
            assertTrue(context.getBeansOfType(RelationClient.class).isEmpty());
        });
    }

    @Test
    void explicitIndependentTransportUsesExistingSettingsAndRedactsSecrets() {
        runner.withPropertyValues("ZOOP_AI_PLAN_ADMISSION_CLIENT_ENABLED=true", "ZOOP_AI_PLAN_ADMISSION_CLIENT_BASE_URL=https://ai.internal.example/ai",
                "ZOOP_AI_PLAN_ADMISSION_CLIENT_TOKEN=" + TOKEN).run(context -> {
                    assertNull(context.getStartupFailure());
                    assertInstanceOf(HttpPlanAdmissionClient.class, context.getBean(PlanAdmissionClient.class));
                    var properties = context.getBean(AiPlanAdmissionClientProperties.class);
                    assertEquals(16_000_000, properties.maxResponseBytes());
                    assertEquals("/ai", properties.toSettings().baseUri().getPath());
                    assertFalse(properties.toString().contains(TOKEN));
                    assertTrue(context.getBeansOfType(ExtractionClient.class).isEmpty());
                    assertTrue(context.getBeansOfType(RelationClient.class).isEmpty());
                });
    }

    @Test
    void badEnabledTransportFailsClosedWithOnlyItsSettingName() {
        for (String bad : new String[]{"ZOOP_AI_PLAN_ADMISSION_CLIENT_BASE_URL=http://outside.example",
                "ZOOP_AI_PLAN_ADMISSION_CLIENT_TOKEN=short", "ZOOP_AI_PLAN_ADMISSION_CLIENT_REQUEST_TIMEOUT=0s",
                "ZOOP_AI_PLAN_ADMISSION_CLIENT_MAX_RESPONSE_BYTES=1"}) {
            runner.withPropertyValues("ZOOP_AI_PLAN_ADMISSION_CLIENT_ENABLED=true", "ZOOP_AI_PLAN_ADMISSION_CLIENT_BASE_URL=https://ai.internal.example",
                    "ZOOP_AI_PLAN_ADMISSION_CLIENT_TOKEN=" + TOKEN, bad).run(context -> {
                        assertNotNull(context.getStartupFailure());
                        AiClientConfigurationException named = null;
                        for (Throwable error = context.getStartupFailure(); error != null; error = error.getCause()) {
                            assertFalse(String.valueOf(error.getMessage()).contains(TOKEN));
                            if (error instanceof AiClientConfigurationException configuration) {
                                named = configuration;
                            }
                        }
                        assertNotNull(named);
                        assertTrue(named.getMessage().startsWith("zoop.ai.plan-admission-client."));
                    });
        }
    }
}
