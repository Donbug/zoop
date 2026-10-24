package com.zoop.chat.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import com.zoop.common.exception.CustomException;
import com.zoop.document.evidence.service.EvidenceService.Readability;
import com.zoop.graph.read.GraphContextLookup;
import com.zoop.graph.read.PublicGraphReader;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The company catalog profile as one citable quote ({@code Citation.sourceKind=company_profile}): ZOOP's own reviewed
 * catalog text (business summary, legal name, representative, founding date, sector, website), never an article. Its id has
 * the evidence id shape and is the SHA-256 of the company id and the quoted text, so an answer stays tied to the text it
 * quoted: once the catalog changes that text, the old id no longer resolves and a stored answer citing it is withheld.
 * Only a company with a business summary has a profile quote.
 *
 * <p>A quote is readable under the same public boundary as the company itself ({@link #readability}): the company must be
 * visible in the pinned graph at the run's asOf with the current exclusions. The catalog keeps only its current text, so at
 * an explicit asOf the quote stands only when the company row has not changed since then.
 */
@Component
public class ChatCompanyProfiles {
    /** The chat grant registry's source id for the catalog text. */
    public static final String SOURCE_ID = "zoop-company-catalog";
    public static final String PUBLISHER = "줍 기업 카탈로그";

    /**
     * One company's profile quote. {@code url} is the company's own website, null when the catalog has none;
     * {@code updatedAt} is when the company row last changed.
     */
    public record Quote(String evidenceId, String companyId, String name, String text, String url, Instant updatedAt) {
        public String title() {
            return name + " 기업 개요";
        }
    }

    /** Every current quote by id, as of one catalog revision. */
    private record Catalog(long revision, Map<String, Quote> byId) { }

    private final NamedParameterJdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final PublicGraphReader graphs;
    private volatile Catalog catalog;

    public ChatCompanyProfiles(NamedParameterJdbcTemplate jdbc, ObjectMapper mapper, PublicGraphReader graphs) {
        this.jdbc = jdbc;
        this.mapper = mapper;
        this.graphs = graphs;
    }

    /** The profile quote of a catalog company, or empty when it is not in the catalog or has no business summary. */
    public Optional<Quote> forCompany(String companyId) {
        return read("WHERE id = :id", new MapSqlParameterSource("id", companyId)).stream().findFirst();
    }

    /**
     * The profile quote an id names now, or empty when no current catalog text has that id. The quotes are read again only
     * when the catalog revision has moved, so checking every citation of an answer costs one revision read each.
     */
    public Optional<Quote> byId(String evidenceId) {
        if (evidenceId == null || !evidenceId.startsWith("ev-")) return Optional.empty();
        // The revision is read before the rows: rows newer than it are read again on the next change, never kept stale.
        long revision = jdbc.queryForObject("SELECT revision FROM company_catalog_revision", new MapSqlParameterSource(),
                Long.class);
        Catalog current = catalog;
        if (current == null || current.revision() != revision) {
            Map<String, Quote> quotes = new HashMap<>();
            read("", new MapSqlParameterSource()).forEach(q -> quotes.put(q.evidenceId(), q));
            current = new Catalog(revision, Map.copyOf(quotes));
            catalog = current;
        }
        return Optional.ofNullable(current.byId().get(evidenceId));
    }

    /**
     * Whether a profile quote may be shown for a run at {@code graphVersion} and {@code asOf}: its company visible there through
     * the public graph read, and its text unchanged since an explicit asOf. A version, snapshot or database that cannot be
     * read is {@code UNAVAILABLE}, never a denial.
     */
    public Readability readability(Quote quote, String graphVersion, Instant asOf, String requestId) {
        if (asOf != null && (quote.updatedAt() == null || quote.updatedAt().isAfter(asOf))) return Readability.DENIED;
        if (graphVersion == null) return Readability.DENIED;
        try {
            var pinned = graphs.read(null, graphVersion, asOf, requestId);
            return new GraphContextLookup(pinned.graph()).find(quote.companyId()).filter(t -> "company".equals(t.kind()))
                    .isPresent() ? Readability.READABLE : Readability.DENIED;
        } catch (CustomException | DataAccessException | TransactionException unavailable) {
            return Readability.UNAVAILABLE;
        }
    }

    /**
     * {@link #readability} for an id: empty when it names no current profile quote, {@code UNAVAILABLE} when the catalog
     * cannot be read.
     */
    public Optional<Readability> check(String evidenceId, String graphVersion, Instant asOf, String requestId) {
        Optional<Quote> quote;
        try {
            quote = byId(evidenceId);
        } catch (DataAccessException | TransactionException unavailable) {
            return Optional.of(Readability.UNAVAILABLE);
        }
        return quote.map(q -> readability(q, graphVersion, asOf, requestId));
    }

    private List<Quote> read(String where, MapSqlParameterSource parameters) {
        List<Quote> quotes = new ArrayList<>();
        jdbc.query("SELECT id, name, profile::text AS profile, updated_at FROM companies " + where + " ORDER BY id",
                parameters, rs -> {
                    String profile = rs.getString("profile");
                    if (profile == null) return;
                    Timestamp updated = rs.getTimestamp("updated_at");
                    quote(rs.getString("id"), rs.getString("name"), mapper.readTree(profile),
                            updated == null ? null : updated.toInstant()).ifPresent(quotes::add);
                });
        return quotes;
    }

    static Optional<Quote> quote(String companyId, String name, JsonNode profile, Instant updatedAt) {
        String summary = text(profile, "businessSummary");
        if (summary == null) return Optional.empty();
        StringBuilder text = new StringBuilder(name).append('(').append(companyId).append(") 사업 개요: ").append(summary);
        append(text, "정식 법인명", text(profile, "legalName"));
        append(text, "대표", text(profile, "representative"));
        append(text, "설립일", text(profile, "foundedDate"));
        append(text, "업종 분류", text(profile, "sector"));
        String url = text(profile, "websiteUrl");
        append(text, "홈페이지", url);
        String quoted = text.toString();
        return Optional.of(new Quote(id(companyId, quoted), companyId, name, quoted, url, updatedAt));
    }

    private static void append(StringBuilder text, String label, String value) {
        if (value != null) text.append(' ').append(label).append(": ").append(value).append('.');
    }

    private static String text(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value == null || !value.isString() || value.stringValue().isBlank() ? null : value.stringValue().strip();
    }

    static String id(String companyId, String text) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(("company_profile\n" + companyId + "\n" + text).getBytes(StandardCharsets.UTF_8));
            return "ev-" + HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
