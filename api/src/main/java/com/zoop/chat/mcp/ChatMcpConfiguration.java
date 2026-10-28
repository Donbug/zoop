package com.zoop.chat.mcp;

import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.orchestrator.ChatModels;
import com.zoop.chat.repository.ChatExecutionRepository;
import org.springframework.beans.factory.ObjectProvider;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRunner;
import io.modelcontextprotocol.common.McpTransportContext;
import io.modelcontextprotocol.json.jackson3.JacksonMcpJsonMapper;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpStatelessSyncServer;
import io.modelcontextprotocol.server.transport.HttpServletStatelessServerTransport;
import io.modelcontextprotocol.spec.McpSchema;
import java.time.Clock;
import java.time.Duration;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.boot.web.servlet.ServletRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import tools.jackson.databind.json.JsonMapper;

/**
 * The chat MCP endpoint, registered only with {@code zoop.chat.mcp.enabled=true} (api/docs/chat-mcp.md): a stateless MCP
 * server over Streamable HTTP at {@code /mcp} (POST with a JSON response; no sessions, no server-sent streams), behind
 * {@link ChatMcpAccessFilter}. It lives in the application because the application owns the data; the model provider's
 * runtime calls it with a job-scoped grant token, and the AI service never reads application data through it.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "zoop.chat.mcp.enabled", havingValue = "true")
public class ChatMcpConfiguration {
    static final String PATH = "/mcp";
    /** Largest MCP request body accepted (413 above it). */
    static final int MAX_REQUEST_BYTES = 64 * 1024;
    /** A tool call's own limits are the runner's; this only bounds the SDK's wait for a handler. */
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(15);
    /** The MCP wire's own JSON mapping, independent of the application's web JSON settings. */
    private static final JsonMapper PROTOCOL_JSON = JsonMapper.builder().build();

    @Bean
    ChatMcpGrants chatMcpGrants(@Value("${ZOOP_CHAT_MCP_ACTIVE_KEY_ID:}") String activeKeyId,
            @Value("${ZOOP_CHAT_MCP_KEYS:}") String keys, Clock clock) {
        return new ChatMcpGrants(activeKeyId, keys, clock);
    }

    @Bean
    ChatMcpTools chatMcpTools(ChatToolRegistry registry, ChatToolRunner runner, ChatJobExecutor executor) {
        return new ChatMcpTools(registry, runner, executor, PROTOCOL_JSON);
    }

    /**
     * The agent path, only with {@code zoop.chat.mcp.agent-enabled=true}: runs take it when their plan fits, through the chat
     * model stages ({@code zoop.ai.chat-client.enabled=true}); enabled without them, startup fails naming the setting. The URL
     * the provider calls this endpoint at is the AI runtime operator's ({@code ZOOP_AI_CHAT_MCP_SERVER_URL}), never sent from here.
     */
    @Bean
    @ConditionalOnProperty(name = "zoop.chat.mcp.agent-enabled", havingValue = "true")
    ChatMcpAgent chatMcpAgent(ObjectProvider<ChatModels.Agent> agent, ChatMcpTools tools, ChatMcpGrants grants,
            ChatExecutionRepository runs) {
        ChatModels.Agent stages = agent.getIfAvailable();
        if (stages == null) {
            throw new IllegalStateException("zoop.chat.mcp.agent-enabled needs the chat model stages (zoop.ai.chat-client.enabled)");
        }
        return new ChatMcpAgent(stages, tools, grants, runs, PROTOCOL_JSON);
    }

    @Bean(destroyMethod = "")
    HttpServletStatelessServerTransport chatMcpTransport() {
        return transport(PROTOCOL_JSON);
    }

    @Bean(destroyMethod = "close")
    McpStatelessSyncServer chatMcpServer(HttpServletStatelessServerTransport transport, ChatMcpTools tools) {
        return server(transport, tools, PROTOCOL_JSON);
    }

    @Bean
    ServletRegistrationBean<HttpServletStatelessServerTransport> chatMcpServlet(
            HttpServletStatelessServerTransport transport, McpStatelessSyncServer server) {
        // The server is a dependency so the transport has its handler before the first request.
        var registration = new ServletRegistrationBean<>(transport, PATH);
        registration.setName("chatMcp");
        return registration;
    }

    @Bean
    FilterRegistrationBean<ChatMcpAccessFilter> chatMcpAccessFilter(ChatMcpGrants grants, Clock clock) {
        var registration = new FilterRegistrationBean<>(new ChatMcpAccessFilter(grants, clock));
        registration.addUrlPatterns(PATH);
        registration.setName("chatMcpAccess");
        return registration;
    }

    /** The servlet transport; its MCP context carries only the grant {@link ChatMcpAccessFilter} verified. */
    static HttpServletStatelessServerTransport transport(JsonMapper mapper) {
        return HttpServletStatelessServerTransport.builder().jsonMapper(new JacksonMcpJsonMapper(mapper))
                .messageEndpoint(PATH).maxRequestSize(MAX_REQUEST_BYTES)
                .contextExtractor(request -> request.getAttribute(ChatMcpAccessFilter.GRANT_ATTRIBUTE)
                        instanceof ChatMcpGrant grant ? McpTransportContext.create(Map.of(ChatMcpTools.GRANT, grant))
                        : McpTransportContext.EMPTY)
                .build();
    }

    /** The MCP server on {@code transport}: tools only, each listed only to a grant that allows it. */
    static McpStatelessSyncServer server(HttpServletStatelessServerTransport transport, ChatMcpTools tools,
            JsonMapper mapper) {
        return McpServer.sync(transport).jsonMapper(new JacksonMcpJsonMapper(mapper))
                .serverInfo("zoop-chat", "1")
                .capabilities(McpSchema.ServerCapabilities.builder().tools(false).build())
                .requestTimeout(REQUEST_TIMEOUT)
                .addToolFilter(ChatMcpTools::visible)
                .tools(tools.specifications())
                .build();
    }
}
