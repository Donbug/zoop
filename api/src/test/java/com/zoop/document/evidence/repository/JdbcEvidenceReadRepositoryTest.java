package com.zoop.document.evidence.repository;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;

class JdbcEvidenceReadRepositoryTest {
    @Test
    void executionRecipientsQueryIncludesSentimentGenerationStage() {
        NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);
        AtomicReference<String> executedSql = new AtomicReference<>();
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class))).thenAnswer(call -> {
            executedSql.set(call.getArgument(0));
            return List.of();
        });

        new JdbcEvidenceReadRepository(jdbc).executionRecipients("job-1", "analysis-1", "grant-1", "r1");

        assertTrue(executedSql.get().contains("'document-sentiment'"));
    }
}
