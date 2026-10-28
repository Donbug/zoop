package com.zoop.graph.read;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;
import org.springframework.dao.QueryTimeoutException;
import org.springframework.jdbc.core.RowCallbackHandler;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;

class JdbcDisclosureExclusionReaderTest {
    @Test
    void anUnreadableStoreIsSourceUnavailableNeverAnEmptyOverlay() {
        NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);
        doThrow(new QueryTimeoutException("timeout")).when(jdbc)
                .query(anyString(), any(SqlParameterSource.class), any(RowCallbackHandler.class));

        CustomException failure = assertThrows(CustomException.class, () -> new JdbcDisclosureExclusionReader(jdbc).current("gv-1"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure.getErrorCode());
    }
}
