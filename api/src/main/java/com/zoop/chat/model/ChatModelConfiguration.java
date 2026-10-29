package com.zoop.chat.model;

import java.time.Clock;
import java.util.Optional;

import com.zoop.ai.config.AiChatClientProperties;
import com.zoop.ai.http.HttpChatStageClient;
import com.zoop.chat.orchestrator.ChatAgentPath;
import com.zoop.chat.orchestrator.ChatCitationSource;
import com.zoop.chat.orchestrator.OrchestratedChatEngine;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.graph.read.PublicGraphReader;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

/**
 * Registers the chatbot engine only when {@code zoop.ai.chat-client.enabled=true}: the chat stage client, the model stage
 * adapters and the {@link OrchestratedChatEngine}. Without it no engine exists and {@code zoop.chat.questions-enabled} must stay
 * off (startup refuses the opposite). An invalid client setting fails startup with the setting's name.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "zoop.ai.chat-client", name = "enabled", havingValue = "true")
@EnableConfigurationProperties(AiChatClientProperties.class)
public class ChatModelConfiguration {

    @Bean
    HttpChatStageClient aiChatStageClient(AiChatClientProperties properties) {
        return new HttpChatStageClient(properties.toSettings());
    }

    @Bean
    ChatModelStages chatModelStages(HttpChatStageClient client, AiChatClientProperties properties,
            NamedParameterJdbcTemplate jdbc, PublicGraphReader graphs, ChatCitationSource citations, Clock clock) {
        ChatModelStages.ArticleSources sources = articleId -> Optional.ofNullable(jdbc.query(
                "SELECT provider FROM articles WHERE id = :id", new MapSqlParameterSource("id", articleId),
                rs -> rs.next() ? rs.getString(1) : null));
        return new ChatModelStages(client, properties.validatedMode(), new CompanyNameResolver(jdbc),
                new IssueNameResolver(graphs), citations, sources, new ChatModelRecorder(jdbc, clock));
    }

    @Bean
    OrchestratedChatEngine chatEngine(ChatModelStages stages, ChatToolRegistry registry, ChatToolRunner runner,
            ChatCitationSource citations, Clock clock, ObjectProvider<ChatAgentPath> agent) {
        // The agent path exists only with the MCP endpoint and its agent flag on (ChatMcpConfiguration); otherwise direct.
        return new OrchestratedChatEngine(stages, stages, stages, registry, runner, citations, clock, agent.getIfAvailable());
    }
}
