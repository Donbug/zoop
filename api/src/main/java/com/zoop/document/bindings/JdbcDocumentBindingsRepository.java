package com.zoop.document.bindings;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import com.zoop.document.bindings.BindingSelection.VersionKey;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

/** {@link DocumentBindingsRepository} over the real registry tables: plain statements, no lock, no write, no ORDER BY. */
public class JdbcDocumentBindingsRepository implements DocumentBindingsRepository {
    /** Keys per statement of {@link #findVersions}: well under the driver's parameter limit, in tuples of two. */
    static final int CHUNK = 1_000;
    private static final String SELECT = """
            SELECT v.article_id, v.version, v.text_artifact_id, r.access_status, a.kind, a.sha256
            FROM article_versions v
            JOIN articles r ON r.id = v.article_id
            JOIN artifacts a ON a.id = v.text_artifact_id
            """;
    private static final String AVAILABLE_ONLY = "WHERE r.access_status = 'available'\n";
    private static final String SELECTED = "WHERE (v.article_id, v.version) IN (:keys)\n";
    private static final String COUNT_EXCLUDED = """
            SELECT r.access_status, count(*) AS versions
            FROM article_versions v
            JOIN articles r ON r.id = v.article_id
            WHERE r.access_status <> 'available'
            GROUP BY r.access_status
            """;
    private static final RowMapper<BindingRow> ROW = (rs, rowNumber) -> new BindingRow(rs.getString("article_id"),
            rs.getString("version"), rs.getString("text_artifact_id"), rs.getString("access_status"), rs.getString("kind"),
            rs.getString("sha256"));

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcDocumentBindingsRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public List<BindingRow> listVersions(boolean availableOnly) {
        return jdbc.query(availableOnly ? SELECT + AVAILABLE_ONLY : SELECT, new MapSqlParameterSource(), ROW);
    }

    @Override
    public Map<String, Integer> countExcludedByStatus() {
        Map<String, Integer> counts = new TreeMap<>();
        jdbc.query(COUNT_EXCLUDED, new MapSqlParameterSource(), rs -> {
            counts.put(rs.getString("access_status"), Math.toIntExact(rs.getLong("versions")));
        });
        return counts;
    }

    @Override
    public List<BindingRow> findVersions(Collection<VersionKey> keys) {
        List<VersionKey> all = List.copyOf(keys);
        List<BindingRow> rows = new ArrayList<>();
        for (int from = 0; from < all.size(); from += CHUNK) {
            List<Object[]> tuples = new ArrayList<>();
            for (VersionKey key : all.subList(from, Math.min(all.size(), from + CHUNK))) {
                tuples.add(new Object[] {key.documentId(), key.documentVersion()});
            }
            // A list of Object[] expands to a list of (?, ?) tuples, which PostgreSQL matches against the row value.
            rows.addAll(jdbc.query(SELECT + SELECTED, new MapSqlParameterSource("keys", tuples), ROW));
        }
        return rows;
    }
}
