package com.zoop.graph.read;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.sql.ResultSet;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;
import org.springframework.dao.QueryTimeoutException;
import org.springframework.jdbc.core.RowCallbackHandler;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;

class JdbcDisclosureExclusionReaderTest {
    @Test
    void returnsArticleExclusionsBoundToTheirExactVersion() throws Exception {
        NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);
        ResultSet row = mock(ResultSet.class);
        when(row.getLong("revision")).thenReturn(12L);
        when(row.getString("target_kind")).thenReturn("article");
        when(row.getString("target_id")).thenReturn("doc-123");
        when(row.getString("article_version")).thenReturn("v7");
        doAnswer(call -> {
            ((RowCallbackHandler) call.getArgument(2)).processRow(row);
            return null;
        }).when(jdbc).query(anyString(), any(SqlParameterSource.class), any(RowCallbackHandler.class));

        DisclosureExclusions actual = new JdbcDisclosureExclusionReader(jdbc).current("gv-one");

        assertEquals(12L, actual.revision());
        assertEquals(java.util.Set.of(new DisclosureExclusions.ArticleTarget("doc-123", "v7")), actual.articleTargets());
    }

    @Test
    void anUnreadableStoreIsSourceUnavailableNeverAnEmptyOverlay() {
        NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);
        doThrow(new QueryTimeoutException("timeout")).when(jdbc)
                .query(anyString(), any(SqlParameterSource.class), any(RowCallbackHandler.class));

        CustomException failure = assertThrows(CustomException.class, () -> new JdbcDisclosureExclusionReader(jdbc).current("gv-1"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure.getErrorCode());
    }
}
