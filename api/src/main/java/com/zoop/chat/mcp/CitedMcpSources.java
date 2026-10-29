package com.zoop.chat.mcp;

import com.zoop.chat.dto.Citation;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.orchestrator.ChatCitationSource;
import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatZoopDocs;
import com.zoop.chat.tool.ChatToolUnavailable;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * {@link ChatMcpSources} through the run's own citation read ({@link ChatCitationSource}), so an MCP result is placed exactly
 * like a direct path quote: a profile quote is the catalog's, a ZOOP document section ZOOP's documents', an article quote its
 * {@code articles.provider}.
 */
@Component
public class CitedMcpSources implements ChatMcpSources {
    private final ChatCitationSource citations;
    private final NamedParameterJdbcTemplate jdbc;

    public CitedMcpSources(ChatCitationSource citations, NamedParameterJdbcTemplate jdbc) {
        this.citations = citations;
        this.jdbc = jdbc;
    }

    @Override
    public Map<String, String> sourcesOf(ChatRun run, Collection<String> evidenceIds) {
        Map<String, String> sources = new LinkedHashMap<>();
        for (String id : evidenceIds) {
            citations.cite(id, run.graphVersionId(), run.context().asOf(), run.jobId()).flatMap(this::source)
                    .ifPresent(source -> sources.put(id, source));
        }
        return sources;
    }

    private Optional<String> source(Citation citation) {
        return switch (citation.sourceKind()) {
            case "company_profile" -> Optional.of(ChatCompanyProfiles.SOURCE_ID);
            case "zoop_doc" -> Optional.of(ChatZoopDocs.SOURCE_ID);
            case "article" -> citation.articleId() == null ? Optional.empty() : provider(citation.articleId());
            default -> Optional.empty();
        };
    }

    private Optional<String> provider(String articleId) {
        try {
            List<String> rows = jdbc.queryForList("SELECT provider FROM articles WHERE id = :id",
                    new MapSqlParameterSource("id", articleId), String.class);
            return rows.stream().findFirst();
        } catch (DataAccessException unavailable) {
            throw new ChatToolUnavailable("the source of article evidence could not be read", unavailable);
        }
    }
}
