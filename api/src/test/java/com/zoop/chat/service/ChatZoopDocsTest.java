package com.zoop.chat.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import com.zoop.document.evidence.service.EvidenceService.Readability;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;

class ChatZoopDocsTest {
    private static final String BODY = "# 개인정보 처리방침\n\n- 버전: v1\n\n## 1. 처리 목적\n\n이메일을 처리합니다. 😀\n\n"
            + "## 2. 보유 기간\n\n탈퇴하면 지웁니다.\n\n";
    private static final Instant NOW = Instant.parse("2026-10-25T00:00:00Z");

    @Test
    void eachHeadingSectionIsAQuoteWithItsCodePointSpanInTheBody() {
        var quotes = ChatZoopDocs.split("policy.privacy", "v1", "개인정보 처리방침", BODY);
        assertEquals(2, quotes.size());
        var first = quotes.getFirst();
        assertEquals("## 1. 처리 목적\n\n이메일을 처리합니다. 😀", first.text());
        assertEquals("개인정보 처리방침 · 1. 처리 목적", first.title());
        assertEquals(first.text(), codePoints(BODY, first.start(), first.end()), "the span is the quote, in code points");
        var last = quotes.getLast();
        assertEquals("## 2. 보유 기간\n\n탈퇴하면 지웁니다.", last.text());
        assertEquals(last.text(), codePoints(BODY, last.start(), last.end()), "a character outside the BMP counts once");
        assertTrue(first.evidenceId().matches("ev-[0-9a-f]{64}"), "it has the evidence id shape the model stages accept");
    }

    @Test
    void theIdIsTheSameForTheSameVersionAndChangesWithIt() {
        var v1 = ChatZoopDocs.split("policy.privacy", "v1", "개인정보 처리방침", BODY).getFirst();
        assertEquals(v1, ChatZoopDocs.split("policy.privacy", "v1", "개인정보 처리방침", BODY).getFirst());
        assertNotEquals(v1.evidenceId(),
                ChatZoopDocs.split("policy.privacy", "v2", "개인정보 처리방침", BODY).getFirst().evidenceId());
        assertNotEquals(v1.evidenceId(),
                ChatZoopDocs.split("policy.service", "v1", "개인정보 처리방침", BODY).getFirst().evidenceId());
    }

    @Test
    void theApprovedPoliciesFitOneReadAndEverySectionCanBeQuoted() throws Exception {
        int sections = 0;
        for (String file : List.of("privacy-policy-2026-10-13.1.md", "terms-of-service-2026-10-13.1.md")) {
            String body = Files.readString(Path.of("../docs/legal/approved", file)).replace("\r\n", "\n");
            var quotes = ChatZoopDocs.split("policy.x", "2026-10-13.1", "약관", body);
            assertFalse(quotes.isEmpty(), file);
            // ChatModelStages sends a quote of at most 2,000 characters.
            quotes.forEach(q -> assertTrue(q.text().length() <= 2000, q.title()));
            sections += quotes.size();
        }
        assertTrue(sections <= 20, "both policies are passed on whole within one call's limit: " + sections);
    }

    @Test
    void onlyTheVersionInEffectReadsAndAReplacedOneIsDenied() {
        var effective = new AtomicReference<>("v1");
        var docs = new ChatZoopDocs(registry(effective), Clock.fixed(NOW, ZoneOffset.UTC));
        var v1 = docs.inEffect("policy.privacy", null).orElseThrow();
        assertEquals("v1", v1.version());
        assertEquals(2, v1.quotes().size());
        var quote = v1.quotes().getFirst();
        assertEquals(quote, docs.byId(quote.evidenceId()).orElseThrow());
        assertEquals(Readability.READABLE, docs.check(quote.evidenceId(), null).orElseThrow());

        effective.set("v2");
        assertEquals(Readability.DENIED, docs.check(quote.evidenceId(), null).orElseThrow(), "a replaced version");
        effective.set(null);
        assertTrue(docs.inEffect("policy.privacy", null).isEmpty(), "a retired policy");
        assertEquals(Readability.DENIED, docs.readability(quote, null));
    }

    @Test
    void anotherIdIsNotAZoopDocumentAndAnOutageIsUnavailable() {
        var docs = new ChatZoopDocs(registry(new AtomicReference<>("v1")), Clock.fixed(NOW, ZoneOffset.UTC));
        assertTrue(docs.check("ev-" + "f".repeat(64), null).isEmpty());
        assertTrue(docs.check("chat-tool-1", null).isEmpty());
        assertTrue(docs.inEffect("help.map", null).isEmpty(), "only policies are registered");

        var jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class)))
                .thenThrow(new DataAccessResourceFailureException("down"));
        assertEquals(Readability.UNAVAILABLE, new ChatZoopDocs(jdbc, Clock.systemUTC()).check("ev-" + "f".repeat(64), null)
                .orElseThrow());
    }

    /** A registry of {@code privacy} with versions v1 and v2 of {@link #BODY}; {@code effective} is the one in effect. */
    @SuppressWarnings("unchecked")
    private static NamedParameterJdbcTemplate registry(AtomicReference<String> effective) {
        var jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class))).thenAnswer(i -> {
            String sql = i.getArgument(0);
            var mapper = (RowMapper<String[]>) i.getArgument(2);
            List<String[]> rows = new ArrayList<>();
            var rs = mock(java.sql.ResultSet.class);
            if (sql.contains("effective_at")) {
                assertEquals("privacy", ((MapSqlParameterSource) i.getArgument(1)).getValue("term"));
                if (effective.get() == null) return rows;
                when(rs.getString("version")).thenReturn(effective.get());
                when(rs.getString("title_snapshot")).thenReturn("개인정보 처리방침");
                rows.add(mapper.mapRow(rs, 0));
                return rows;
            }
            for (String version : List.of("v1", "v2")) {
                var row = mock(java.sql.ResultSet.class);
                when(row.getString("term_id")).thenReturn("privacy");
                when(row.getString("version")).thenReturn(version);
                when(row.getString("title_snapshot")).thenReturn("개인정보 처리방침");
                rows.add(mapper.mapRow(row, rows.size()));
            }
            return rows;
        });
        when(jdbc.queryForObject(anyString(), any(SqlParameterSource.class), eq(String.class))).thenReturn(BODY);
        return jdbc;
    }

    private static String codePoints(String text, int start, int end) {
        return text.substring(text.offsetByCodePoints(0, start), text.offsetByCodePoints(0, end));
    }
}
