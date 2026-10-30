package com.zoop.chat.tool;

import java.time.Clock;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.junit.jupiter.api.Assertions.*;

/** The web search tool is off by default, and on it runs only with the synthetic provider until a real one is chosen. */
class ChatWebSearchConfigurationTest {
    private final ApplicationContextRunner runner = new ApplicationContextRunner()
            .withUserConfiguration(ChatWebSearchConfiguration.class)
            .withBean(Clock.class, Clock::systemUTC);

    @Test
    void offByDefault() {
        runner.run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(ChatWebSearchTool.class).isEmpty());
        });
    }

    @Test
    void enabledWithoutTheSyntheticProviderRefusesToStart() {
        for (String provider : new String[] {"none", "openai", ""}) {
            runner.withPropertyValues("zoop.chat.web.enabled=true", "zoop.chat.web.provider=" + provider)
                    .run(context -> assertNotNull(context.getStartupFailure(), provider));
        }
        runner.withPropertyValues("zoop.chat.web.enabled=true")
                .run(context -> assertNotNull(context.getStartupFailure(), "no provider named"));
    }

    @Test
    void enabledWithTheSyntheticProviderRegistersTheTool() {
        runner.withPropertyValues("zoop.chat.web.enabled=true", "zoop.chat.web.provider=synthetic").run(context -> {
            assertNull(context.getStartupFailure());
            assertEquals(ChatCapability.WEB_SEARCH, context.getBean(ChatWebSearchTool.class).capability());
            assertEquals(SyntheticWebSearchProvider.ID, context.getBean(ChatWebSearchProvider.class).id());
        });
    }
}
