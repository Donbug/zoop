package com.zoop.ai.config;

import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.handoff.HandoffExposureClient;
import com.zoop.ai.handoff.HandoffReadClient;
import com.zoop.ai.http.HttpHandoffReadClient;
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

class AiHandoffReadClientConfigurationTest {
    private static final String TOKEN = "read-token-0123456789abcdefghijklmnopqrstuvwxyz";
    private final ApplicationContextRunner runner = new ApplicationContextRunner()
            .withInitializer(context -> {
                context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
                context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
            })
            .withInitializer(new ConfigDataApplicationContextInitializer())
            .withUserConfiguration(AiHandoffReadClientConfiguration.class, AiHandoffExposureClientConfiguration.class);

    @Test
    void absentConfigurationIsOffAndIndependentOfTheExposureClient() {
        runner.run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(HandoffReadClient.class).isEmpty());
            assertTrue(context.getBeansOfType(HandoffExposureClient.class).isEmpty());
        });
        runner.withPropertyValues("ZOOP_AI_HANDOFF_EXPOSURE_CLIENT_ENABLED=true",
                "ZOOP_AI_HANDOFF_EXPOSURE_CLIENT_BASE_URL=https://ai.internal.example", "ZOOP_AI_HANDOFF_EXPOSURE_CLIENT_TOKEN=" + TOKEN)
                .run(context -> {
                    assertNull(context.getStartupFailure());
                    assertTrue(context.getBeansOfType(HandoffReadClient.class).isEmpty(), "exposure never implies read");
                });
    }

    @Test
    void enabledRegistersTheHttpClientWithTheDocumentedDefaultsAndRedactsTheToken() {
        runner.withPropertyValues("ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED=true", "ZOOP_AI_HANDOFF_READ_CLIENT_BASE_URL=https://ai.internal.example/ai",
                "ZOOP_AI_HANDOFF_READ_CLIENT_TOKEN=" + TOKEN).run(context -> {
                    assertNull(context.getStartupFailure());
                    assertInstanceOf(HttpHandoffReadClient.class, context.getBean(HandoffReadClient.class));
                    var properties = context.getBean(AiHandoffReadClientProperties.class);
                    assertEquals(16 * 1024 * 1024, properties.maxResponseBytes());
                    assertEquals(java.time.Duration.ofSeconds(60), properties.requestTimeout());
                    assertEquals("/ai", properties.toSettings(context.getBean(AiTransportProperties.class)).baseUri().getPath());
                    assertFalse(properties.toString().contains(TOKEN));
                    assertTrue(context.getBeansOfType(HandoffExposureClient.class).isEmpty());
                });
    }

    @Test
    void badEnabledTransportFailsClosedWithOnlyItsSettingName() {
        for (String bad : new String[]{"ZOOP_AI_HANDOFF_READ_CLIENT_BASE_URL=http://outside.example",
                "ZOOP_AI_HANDOFF_READ_CLIENT_TOKEN=short", "ZOOP_AI_HANDOFF_READ_CLIENT_REQUEST_TIMEOUT=0s",
                "ZOOP_AI_HANDOFF_READ_CLIENT_MAX_RESPONSE_BYTES=1"}) {
            runner.withPropertyValues("ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED=true", "ZOOP_AI_HANDOFF_READ_CLIENT_BASE_URL=https://ai.internal.example",
                    "ZOOP_AI_HANDOFF_READ_CLIENT_TOKEN=" + TOKEN, bad).run(context -> {
                        Throwable failure = context.getStartupFailure();
                        assertNotNull(failure, bad);
                        Throwable cause = failure;
                        while (cause != null && !(cause instanceof AiClientConfigurationException)) {
                            cause = cause.getCause();
                        }
                        assertNotNull(cause, bad);
                        assertTrue(cause.getMessage().startsWith("zoop.ai.handoff-read-client."), cause.getMessage());
                        assertFalse(cause.getMessage().contains(TOKEN), cause.getMessage());
                        assertFalse(cause.getMessage().contains("outside.example"), cause.getMessage());
                    });
        }
    }

    @Test
    void plainHttpReachesOnlyTheListedInVpcHost() {
        String[] client = {"ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED=true", "ZOOP_AI_HANDOFF_READ_CLIENT_TOKEN=" + TOKEN};
        runner.withPropertyValues(client).withPropertyValues("ZOOP_AI_HANDOFF_READ_CLIENT_BASE_URL=http://ai:8000")
                .run(context -> assertEquals("zoop.ai.handoff-read-client.base-url must use https unless the host is loopback or "
                        + "listed in zoop.ai.plaintext-http-hosts", configurationFailure(context.getStartupFailure()).getMessage()));
        runner.withPropertyValues(client).withPropertyValues("ZOOP_AI_HANDOFF_READ_CLIENT_BASE_URL=http://ai:8000",
                "ZOOP_AI_PLAINTEXT_HTTP_HOSTS=ai").run(context -> {
                    assertNull(context.getStartupFailure());
                    assertEquals(java.util.Set.of("ai"), context.getBean(AiTransportProperties.class).hosts());
                    var settings = context.getBean(AiHandoffReadClientProperties.class)
                            .toSettings(context.getBean(AiTransportProperties.class));
                    assertEquals("http://ai:8000", settings.baseUri().toString());
                });
        runner.withPropertyValues(client).withPropertyValues("ZOOP_AI_HANDOFF_READ_CLIENT_BASE_URL=http://outside.example:8000",
                "ZOOP_AI_PLAINTEXT_HTTP_HOSTS=ai").run(context -> assertTrue(configurationFailure(context.getStartupFailure())
                        .getMessage().startsWith("zoop.ai.handoff-read-client.base-url ")));
        runner.withPropertyValues(client).withPropertyValues("ZOOP_AI_HANDOFF_READ_CLIENT_BASE_URL=http://ai:8000",
                "ZOOP_AI_PLAINTEXT_HTTP_HOSTS=*.internal").run(context -> {
                    AiClientConfigurationException failure = configurationFailure(context.getStartupFailure());
                    assertEquals("zoop.ai.plaintext-http-hosts must list lower-case host names only", failure.getMessage());
                });
    }

    private static AiClientConfigurationException configurationFailure(Throwable failure) {
        assertNotNull(failure);
        Throwable cause = failure;
        while (cause != null && !(cause instanceof AiClientConfigurationException)) {
            cause = cause.getCause();
        }
        assertNotNull(cause, String.valueOf(failure));
        return (AiClientConfigurationException) cause;
    }
}
