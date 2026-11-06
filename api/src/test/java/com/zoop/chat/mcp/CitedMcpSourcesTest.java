package com.zoop.chat.mcp;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.zoop.chat.dto.Citation;
import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatZoopDocs;
import com.zoop.chat.tool.ChatToolUnavailable;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;

/**
 * Evidence is placed like a direct path quote: through the run's own citation read at its pinned version and asOf, then the
 * catalog, ZOOP's documents or the article's provider. Synthetic citations only.
 */
class CitedMcpSourcesTest {
    private static Citation cited(String kind, String evidenceId, String articleId) {
        return new Citation(kind, evidenceId, "인용", articleId, null, null, null, 0, 2, null, null, null, null);
    }

    @Test
    void eachEvidenceIsPlacedByWhatItsCitationIsAndAnUncitableOneIsNot() {
        var run = ChatMcpGrantsTest.run("job-00001", 1);
        Map<String, Optional<Citation>> citations = Map.of(
                "ev-a", Optional.of(cited("article", "ev-a", "art-1")),
                "ev-p", Optional.of(cited("company_profile", "ev-p", null)),
                "ev-d", Optional.of(cited("zoop_doc", "ev-d", null)),
                "ev-x", Optional.empty(),
                "ev-n", Optional.of(cited("article", "ev-n", "art-gone")));
        NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.queryForList(any(String.class), any(SqlParameterSource.class), eq(String.class))).thenAnswer(call -> {
            SqlParameterSource params = call.getArgument(1);
            return "art-1".equals(params.getValue("id")) ? List.of("synthetic-news") : List.of();
        });
        var sources = new CitedMcpSources((id, version, asOf, trace) -> {
            assertEquals(run.graphVersionId(), version);
            assertEquals(run.context().asOf(), asOf);
            return citations.get(id);
        }, jdbc);
        assertEquals(Map.of("ev-a", new ChatMcpSources.Evidence("ev-a", "synthetic-news", "인용"),
                "ev-p", new ChatMcpSources.Evidence("ev-p", ChatCompanyProfiles.SOURCE_ID, "인용"),
                "ev-d", new ChatMcpSources.Evidence("ev-d", ChatZoopDocs.SOURCE_ID, "인용")),
                sources.evidenceOf(run, List.of("ev-a", "ev-p", "ev-d", "ev-x", "ev-n")));
    }

    @Test
    void exactBoundedUtf16SpansAreResolvedOncePerUniqueId() {
        var run = ChatMcpGrantsTest.run("job-00001", 1);
        for (String quote : List.of("a".repeat(2000), "é".repeat(2000), "한".repeat(2000),
                "😀".repeat(1000), "\"\\\n한é😀", "", "한".repeat(2001), "😀".repeat(1001))) {
            var reads = new java.util.ArrayList<String>();
            var source = new CitedMcpSources((id, version, asOf, trace) -> {
                reads.add(id);
                assertEquals(run.jobId(), trace);
                return Optional.of(new Citation("company_profile", id, quote, null, null, null, null,
                        0, quote.length(), null, null, null, null));
            }, null);
            var result = source.evidenceOf(run, List.of("ev-p", "ev-p"));
            assertEquals(List.of("ev-p"), reads);
            assertEquals(!quote.isEmpty() && quote.length() <= 2000, result.containsKey("ev-p"));
            if (!result.isEmpty()) assertEquals(quote, result.get("ev-p").quote());
        }
        var mismatched = new CitedMcpSources((id, version, asOf, trace) ->
                Optional.of(cited("company_profile", "ev-other", null)), null);
        assertEquals(Map.of(), mismatched.evidenceOf(run, List.of("ev-p")));
    }

    @Test
    void aSourceThatCannotBeReadIsUnavailableNotAbsent() {
        NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.queryForList(any(String.class), any(SqlParameterSource.class), eq(String.class)))
                .thenThrow(new DataAccessResourceFailureException("down"));
        var sources = new CitedMcpSources((id, version, asOf, trace) -> Optional.of(cited("article", id, "art-1")), jdbc);
        assertThrows(ChatToolUnavailable.class, () -> sources.evidenceOf(ChatMcpGrantsTest.run("job-00001", 1),
                List.of("ev-a")));
    }
}
