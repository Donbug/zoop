package com.zoop.chat.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The company catalog profile as one citable quote ({@code Citation.sourceKind=company_profile}): ZOOP's own reviewed
 * catalog text (business summary, legal name, representative, founding date, sector, website), never an article. Its id has
 * the evidence id shape and is the SHA-256 of the company id and the quoted text, so an answer stays tied to the text it
 * quoted: once the catalog changes that text, the old id no longer resolves and a stored answer citing it is withheld.
 * Only a company with a business summary has a profile quote.
 */
@Component
public class ChatCompanyProfiles {
    /** The chat grant registry's source id for the catalog text. */
    public static final String SOURCE_ID = "zoop-company-catalog";
    public static final String PUBLISHER = "줍 기업 카탈로그";

    /** One company's profile quote. {@code url} is the company's own website, null when the catalog has none. */
    public record Quote(String evidenceId, String companyId, String name, String text, String url) {
        public String title() {
            return name + " 기업 개요";
        }
    }

    private final NamedParameterJdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public ChatCompanyProfiles(NamedParameterJdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    /** The profile quote of a catalog company, or empty when it is not in the catalog or has no business summary. */
    public Optional<Quote> forCompany(String companyId) {
        return read("WHERE id = :id", new MapSqlParameterSource("id", companyId)).stream().findFirst();
    }

    /** The profile quote an id names now, or empty when no current catalog text has that id. */
    public Optional<Quote> byId(String evidenceId) {
        if (evidenceId == null || !evidenceId.startsWith("ev-")) return Optional.empty();
        return read("", new MapSqlParameterSource()).stream().filter(q -> q.evidenceId().equals(evidenceId)).findFirst();
    }

    private List<Quote> read(String where, MapSqlParameterSource parameters) {
        List<Quote> quotes = new ArrayList<>();
        jdbc.query("SELECT id, name, profile::text AS profile FROM companies " + where + " ORDER BY id", parameters, rs -> {
            String profile = rs.getString("profile");
            if (profile == null) return;
            quote(rs.getString("id"), rs.getString("name"), mapper.readTree(profile)).ifPresent(quotes::add);
        });
        return quotes;
    }

    static Optional<Quote> quote(String companyId, String name, JsonNode profile) {
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
        return Optional.of(new Quote(id(companyId, quoted), companyId, name, quoted, url));
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
