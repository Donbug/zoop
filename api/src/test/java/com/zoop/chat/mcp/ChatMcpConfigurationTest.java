package com.zoop.chat.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import com.zoop.chat.executor.ChatEngine;
import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.MemoryChatStore;
import com.zoop.chat.executor.NoChatTransactions;
import com.zoop.chat.orchestrator.ChatModels;
import com.zoop.chat.repository.ChatExecutionRepository;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRunner;
import java.time.Clock;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.boot.web.servlet.ServletRegistrationBean;
import tools.jackson.databind.json.JsonMapper;

/** The chat MCP endpoint exists only when enabled, and enabled it refuses to start without its grant keys. */
class ChatMcpConfigurationTest {
    private final WebApplicationContextRunner runner = new WebApplicationContextRunner()
            .withUserConfiguration(ChatMcpConfiguration.class, ChatAgentFlagCheck.class)
            .withBean(Clock.class, () -> Clock.fixed(ChatMcpGrantsTest.NOW, ZoneOffset.UTC))
            .withBean(ChatToolRegistry.class, () -> new ChatToolRegistry(List.of()))
            .withBean(ChatToolRunner.class, () -> new ChatToolRunner(new ChatToolRegistry(List.of())))
            .withBean(ChatJobExecutor.class, () -> {
                var store = new MemoryChatStore();
                return new ChatJobExecutor(store, store,
                        new StaticListableBeanFactory(Map.of()).getBeanProvider(ChatEngine.class),
                        JsonMapper.builder().build(), Clock.systemUTC(), new NoChatTransactions());
            });

    @Test
    void offByDefaultNothingIsRegistered() {
        runner.run(context -> {
            assertThat(context).hasNotFailed();
            assertThat(context).doesNotHaveBean(ChatMcpGrants.class);
            assertThat(context).doesNotHaveBean(ServletRegistrationBean.class);
        });
    }

    @Test
    void enabledWithoutKeysRefusesToStart() {
        runner.withPropertyValues("zoop.chat.mcp.enabled=true").run(context -> {
            assertThat(context).hasFailed();
            assertThat(context.getStartupFailure()).rootCause().hasMessageContaining("ZOOP_CHAT_MCP_KEYS")
                    .hasMessageNotContaining(ChatMcpGrantsTest.KEY_A);
        });
    }

    @Test
    void enabledWithKeysServesMcpAtItsOwnPath() {
        runner.withPropertyValues("zoop.chat.mcp.enabled=true", "ZOOP_CHAT_MCP_ACTIVE_KEY_ID=k1",
                "ZOOP_CHAT_MCP_KEYS=k1=" + ChatMcpGrantsTest.KEY_A).run(context -> {
                    assertThat(context).hasNotFailed();
                    assertThat(context).hasSingleBean(ChatMcpGrants.class);
                    ServletRegistrationBean<?> servlet = context.getBean(ServletRegistrationBean.class);
                    assertThat(servlet.getUrlMappings()).containsExactly(ChatMcpConfiguration.PATH);
                    assertThat(context).doesNotHaveBean(ChatMcpAgent.class);
                });
    }

    private static final String[] ENABLED = {"zoop.chat.mcp.enabled=true", "ZOOP_CHAT_MCP_ACTIVE_KEY_ID=k1",
            "ZOOP_CHAT_MCP_KEYS=k1=" + ChatMcpGrantsTest.KEY_A, "zoop.chat.mcp.agent-enabled=true"};

    @Test
    void theAgentPathNeedsTheModelStages() {
        var withRepository = runner.withBean(ChatExecutionRepository.class, MemoryChatStore::new);
        withRepository.withPropertyValues(ENABLED).run(context -> assertThat(context.getStartupFailure()).rootCause()
                .hasMessageContaining("zoop.ai.chat-client.enabled"));
        ChatModels.Agent stages = (run, step, input) -> { throw new UnsupportedOperationException(); };
        withRepository.withBean(ChatModels.Agent.class, () -> stages).withPropertyValues(ENABLED)
                .run(context -> assertThat(context).hasSingleBean(ChatMcpAgent.class));
    }

    @Test
    void theAgentFlagWithoutTheMcpEndpointRefusesToStart() {
        runner.withPropertyValues("zoop.chat.mcp.agent-enabled=true").run(context -> assertThat(context.getStartupFailure())
                .rootCause().hasMessageContaining("ZOOP_CHAT_MCP_ENABLED"));
    }
}
