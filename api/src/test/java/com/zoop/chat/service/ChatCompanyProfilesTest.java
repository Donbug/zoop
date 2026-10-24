package com.zoop.chat.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.sql.ResultSet;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.RowCallbackHandler;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

class ChatCompanyProfilesTest {
    private final JsonMapper mapper = JsonMapper.builder().build();

    @Test
    void theQuoteIsTheCatalogTextAndItsIdFollowsThatText() {
        ObjectNode profile = mapper.createObjectNode().put("businessSummary", "메모리 반도체 기업이다.")
                .put("representative", "대표").put("foundedDate", "1969-01-13").put("websiteUrl", "https://example.com");
        var quote = ChatCompanyProfiles.quote("KRX:005930", "삼성전자", profile, null).orElseThrow();
        assertEquals("삼성전자(KRX:005930) 사업 개요: 메모리 반도체 기업이다. 대표: 대표. 설립일: 1969-01-13. "
                + "홈페이지: https://example.com.", quote.text());
        assertEquals("삼성전자 기업 개요", quote.title());
        assertEquals("https://example.com", quote.url());
        assertTrue(quote.evidenceId().matches("ev-[0-9a-f]{64}"), "it has the evidence id shape the model stages accept");
        assertEquals(quote, ChatCompanyProfiles.quote("KRX:005930", "삼성전자", profile, null).orElseThrow());

        profile.put("businessSummary", "바뀐 개요.");
        assertNotEquals(quote.evidenceId(), ChatCompanyProfiles.quote("KRX:005930", "삼성전자", profile, null).orElseThrow()
                .evidenceId(), "changed text is a different quote");
    }

    @Test
    void aCompanyWithoutABusinessSummaryHasNoQuote() {
        ObjectNode profile = mapper.createObjectNode().put("representative", "대표").put("businessSummary", " ");
        assertTrue(ChatCompanyProfiles.quote("KRX:005930", "삼성전자", profile, null).isEmpty());
    }

    @Test
    void theQuotesAreReadAgainOnlyWhenTheCatalogRevisionMoves() throws Exception {
        var jdbc = mock(NamedParameterJdbcTemplate.class);
        var revision = new AtomicLong(1);
        var reads = new AtomicInteger();
        ResultSet row = mock(ResultSet.class);
        when(row.getString("id")).thenReturn("KRX:005930");
        when(row.getString("name")).thenReturn("삼성전자");
        when(row.getString("profile")).thenReturn("{\"businessSummary\":\"메모리 반도체 기업이다.\"}");
        when(row.getTimestamp("updated_at")).thenReturn(Timestamp.from(Instant.parse("2026-10-05T00:00:00Z")));
        when(jdbc.queryForObject(anyString(), any(SqlParameterSource.class), eq(Long.class))).thenAnswer(i -> revision.get());
        doAnswer(i -> {
            reads.incrementAndGet();
            i.<RowCallbackHandler>getArgument(2).processRow(row);
            return null;
        }).when(jdbc).query(anyString(), any(SqlParameterSource.class), any(RowCallbackHandler.class));
        var catalog = new ChatCompanyProfiles(jdbc, mapper, null);
        String id = ChatCompanyProfiles.quote("KRX:005930", "삼성전자",
                mapper.createObjectNode().put("businessSummary", "메모리 반도체 기업이다."), null).orElseThrow().evidenceId();

        assertEquals("KRX:005930", catalog.byId(id).orElseThrow().companyId());
        assertEquals(Instant.parse("2026-10-05T00:00:00Z"), catalog.byId(id).orElseThrow().updatedAt());
        assertTrue(catalog.byId("ev-" + "f".repeat(64)).isEmpty());
        assertEquals(1, reads.get(), "one catalog read serves every id while the revision stands");

        revision.incrementAndGet();
        assertTrue(catalog.byId(id).isPresent());
        assertEquals(2, reads.get());
    }

    @Test
    void anIdThatIsNotAnEvidenceIdReadsNothing() {
        var jdbc = mock(NamedParameterJdbcTemplate.class);
        assertTrue(new ChatCompanyProfiles(jdbc, mapper, null).byId("chat-tool-1").isEmpty());
        verifyNoInteractions(jdbc);
    }
}
