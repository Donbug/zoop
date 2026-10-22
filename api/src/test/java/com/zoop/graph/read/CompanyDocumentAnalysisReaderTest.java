package com.zoop.graph.read;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.document.evidence.repository.EvidenceReadRepository;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.ResultSet;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;

class CompanyDocumentAnalysisReaderTest {
    @TempDir Path temp;
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private static final ArticleRow ARTICLE = new ArticleRow("art-1", "news", "src", "v1", "available");
    private static final VersionRow VERSION = new VersionRow("art-1", "v1", "title", "publisher", null,
            NOW, null, "datetime", null, "text-1", NOW);

    private CompanyDocumentAnalysisReader reader(EvidenceReadRepository evidenceRows, Path grants) throws Exception {
        NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class))).thenAnswer(call -> {
            MapSqlParameterSource params = call.getArgument(1);
            if (!"sentiment".equals(params.getValue("stage"))) return List.of();
            ResultSet row = mock(ResultSet.class);
            Map<String, String> fields = Map.ofEntries(Map.entry("id", "analysis-1"), Map.entry("status", "available"),
                    Map.entry("result_version", "result-1"), Map.entry("result_artifact_id", "artifact-1"),
                    Map.entry("exact_receipt_id", "exact-analysis-1"), Map.entry("semantic_receipt_id", "semantic-1"),
                    Map.entry("result_text", """
                            {"label":"positive","companyId":"KRX:000660","rationale":"좋음","quotes":[],
                             "judgedAt":"2026-10-16T12:00:00Z","model":"replay","promptVersion":"p1"}
                            """), Map.entry("grant_reference", "grant-1"), Map.entry("grant_revision", "r1"),
                    Map.entry("ai_job_id", "job-1"));
            when(row.getString(anyString())).thenAnswer(field -> fields.get(field.getArgument(0)));
            @SuppressWarnings("unchecked") RowMapper<Object> mapper = call.getArgument(2);
            return List.of(mapper.mapRow(row, 0));
        });
        DocumentReadProperties properties = mock(DocumentReadProperties.class);
        when(properties.grantsPath()).thenReturn(grants);
        return new CompanyDocumentAnalysisReader(jdbc, evidenceRows, mock(EvidenceService.class),
                mock(DocumentRegistryRepository.class), properties,
                Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void availableSentimentRequiresCurrentGrantAndProvenRecipients() throws Exception {
        Path file = temp.resolve("grants.json");
        Files.writeString(file, """
                {"schemaVersion":"zoop-ai-s1-1","grants":[{"grantId":"grant-1","revision":"r1",
                 "sourceId":"src","enabled":true,"rights":"known",
                 "allowedOperations":["read","store","model-send","quote-display"],
                 "recipients":["authored-replay"],
                 "purposes":["document-summary","document-sentiment","semantic-verification"],
                 "evidence":["authored"],"expiresAt":null}]}
                """);
        EvidenceReadRepository rows = mock(EvidenceReadRepository.class);
        when(rows.executionsExist("job-1")).thenReturn(true);
        when(rows.executionRecipients("job-1", "analysis-1", "grant-1", "r1"))
                .thenReturn(Map.of("document-sentiment", Set.of("authored-replay"),
                        "semantic-verification", Set.of("authored-replay")));
        var reader = reader(rows, file);
        var visible = reader.read(ARTICLE, VERSION, "KRX:000660", "req-1");
        assertEquals("positive", visible.sentiment().get("label").stringValue());
        assertEquals("available", visible.status().sentiment().status());
        assertEquals("result-1", visible.resultVersion());
        assertNull(visible.summary());

        Files.writeString(file, Files.readString(file).replace("\"enabled\":true", "\"enabled\":false"));
        var withdrawn = reader.read(ARTICLE, VERSION, "KRX:000660", "req-2");
        assertNull(withdrawn.sentiment());
        assertEquals("withheld", withdrawn.status().sentiment().status());
    }

    @Test
    void cacheResultWithoutCreatorProofIsWithheld() throws Exception {
        var rows = mock(EvidenceReadRepository.class);
        var result = reader(rows, temp.resolve("not-needed.json")).read(ARTICLE, VERSION, "KRX:000660", "req");
        assertNull(result.sentiment());
        assertEquals("withheld", result.status().sentiment().status());
        assertTrue(result.status().summary().status().equals("not_requested"));
    }
}
