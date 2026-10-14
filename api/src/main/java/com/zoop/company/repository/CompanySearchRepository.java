package com.zoop.company.repository;

import java.sql.Array;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;

import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class CompanySearchRepository {
    private static final String NORMALIZED = "zoop_normalize_company_text";
    private final NamedParameterJdbcTemplate jdbc;

    public CompanySearchRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void lockCatalogForSnapshot() {
        // Acquire before the first snapshot read: TRUNCATE is not MVCC-safe.
        jdbc.getJdbcTemplate().execute("LOCK TABLE companies IN ACCESS SHARE MODE");
    }

    public long catalogRevision() {
        return jdbc.getJdbcTemplate().queryForObject(
                "SELECT revision FROM company_catalog_revision WHERE singleton = true", Long.class);
    }

    public String normalize(String value) {
        return jdbc.getJdbcTemplate().queryForObject(
                "SELECT " + NORMALIZED + "(?)", String.class, value);
    }

    public List<CompanySearchRow> search(String query, CompanySearchPosition after, Long fetchLimit) {
        boolean filtered = !query.isEmpty();
        String rank = filtered
                ? "CASE WHEN " + exactIdentity() + " THEN 0 WHEN " + exactName() + " THEN 1 ELSE 2 END"
                : "2";
        StringBuilder sql = new StringBuilder("""
                SELECT c.id, c.ticker, c.exchange_code, c.name, c.market, c.aliases,
                       c.brand_color, c.logo_url, c.profile ->> 'sector' AS sector,
                       %s AS match_rank
                FROM companies c
                WHERE 1 = 1
                """.formatted(rank));
        MapSqlParameterSource parameters = new MapSqlParameterSource("q", query);

        if (filtered) {
            sql.append(" AND (").append(exactIdentity()).append(" OR ").append(exactName())
                    .append(" OR (c.search_text LIKE :pattern ESCAPE E'\\\\' AND ")
                    .append(partialRecheck()).append(") OR ")
                    .append(partialIdentity()).append(")");
            parameters.addValue("pattern", "%" + escapeLike(query) + "%");
        }
        if (after != null) {
            sql.append(" AND (").append(rank).append(", c.name, c.id) > (:afterRank, :afterName, :afterId)");
            parameters.addValue("afterRank", after.rank())
                    .addValue("afterName", after.name())
                    .addValue("afterId", after.id());
        }
        sql.append(" ORDER BY match_rank, c.name, c.id");
        if (fetchLimit != null) {
            sql.append(" LIMIT :fetchLimit");
            parameters.addValue("fetchLimit", fetchLimit);
        }
        return jdbc.query(sql.toString(), parameters, ROW_MAPPER);
    }

    private static String exactIdentity() {
        return "(c.id = :q OR " + normalized("c.id") + " = :q OR (c.ticker IS NOT NULL AND "
                + normalized("c.ticker") + " = :q))";
    }

    private static String exactName() {
        return "c.name_key = :q";
    }

    private static String partialRecheck() {
        return "(" + normalized("c.name") + " LIKE :pattern ESCAPE E'\\\\' OR EXISTS "
                + "(SELECT 1 FROM unnest(c.aliases) a(value) WHERE " + normalized("a.value")
                + " LIKE :pattern ESCAPE E'\\\\'))";
    }

    private static String partialIdentity() {
        return "(" + normalized("c.id") + " LIKE :pattern ESCAPE E'\\\\' OR (c.ticker IS NOT NULL AND "
                + normalized("c.ticker") + " LIKE :pattern ESCAPE E'\\\\'))";
    }

    private static String normalized(String expression) {
        return NORMALIZED + "(" + expression + ")";
    }

    private static String escapeLike(String value) {
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }

    private static final RowMapper<CompanySearchRow> ROW_MAPPER = (result, rowNumber) -> {
        Array sqlArray = result.getArray("aliases");
        List<String> aliases = new ArrayList<>();
        if (sqlArray != null) {
            try {
                Object[] values = (Object[]) sqlArray.getArray();
                for (Object value : values) {
                    aliases.add((String) value);
                }
            } finally {
                try {
                    sqlArray.free();
                } catch (SQLException ignored) {
                    // Releasing the JDBC array is best effort after materializing its values.
                }
            }
        }
        return new CompanySearchRow(
                result.getString("id"), result.getString("ticker"), result.getString("exchange_code"),
                result.getString("name"), result.getString("market"), List.copyOf(aliases),
                result.getString("brand_color"), result.getString("logo_url"),
                result.getString("sector"), result.getInt("match_rank"));
    };
}
