package com.zoop.chat.model;

import java.sql.Array;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

/**
 * Resolves company names written in a question to catalog ids (provisional decision of 2026-10-22): only an exact catalog name or
 * alias counts, matched as written (latin letters case-insensitively), and the longest match wins where two overlap
 * ("삼성전자" over "삼성"). A name shared by several companies is a {@link Mention} with several candidates: the orchestrator asks
 * which one instead of guessing. The router model never resolves names.
 */
public class CompanyNameResolver {
    /** One catalog company. */
    public record Company(String id, String name, String ticker) {
        /** How a clarification offers it: the name with its ticker (or id), since a shared name alone cannot tell them apart. */
        public String label() {
            return name + " (" + (ticker == null || ticker.isBlank() ? id : ticker) + ")";
        }
    }

    /** A name found in the text and every catalog company it names. */
    public record Mention(String text, List<Company> companies) {
        public boolean ambiguous() {
            return companies.size() > 1;
        }
    }

    record Entry(String key, Company company) { }

    private static final int MIN_NAME = 2;

    private final NamedParameterJdbcTemplate jdbc;

    public CompanyNameResolver(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** Mentions in {@code text}, in order of appearance. */
    public List<Mention> mentions(String text) {
        return match(text, entries());
    }

    private List<Entry> entries() {
        List<Entry> entries = new ArrayList<>();
        jdbc.query("SELECT id, name, ticker, aliases FROM companies ORDER BY id", new MapSqlParameterSource(), rs -> {
            Company company = new Company(rs.getString("id"), rs.getString("name"), rs.getString("ticker"));
            add(entries, company.name(), company);
            for (String alias : aliases(rs.getArray("aliases"))) add(entries, alias, company);
        });
        return entries;
    }

    private static String[] aliases(Array array) throws SQLException {
        if (array == null) return new String[0];
        Object value = array.getArray();
        return value instanceof String[] strings ? strings : new String[0];
    }

    private static void add(List<Entry> entries, String name, Company company) {
        if (name == null) return;
        String key = name.strip().toLowerCase(Locale.ROOT);
        if (key.codePointCount(0, key.length()) >= MIN_NAME) entries.add(new Entry(key, company));
    }

    /** Longest non-overlapping exact occurrences of catalog names or aliases. Pure: the catalog is passed in. */
    static List<Mention> match(String text, List<Entry> entries) {
        String haystack = text.toLowerCase(Locale.ROOT);
        Map<String, List<Company>> byKey = new LinkedHashMap<>();
        for (Entry entry : entries) {
            List<Company> companies = byKey.computeIfAbsent(entry.key(), k -> new ArrayList<>());
            if (companies.stream().noneMatch(c -> c.id().equals(entry.company().id()))) companies.add(entry.company());
        }
        List<String> keys = new ArrayList<>(byKey.keySet());
        keys.sort(Comparator.comparingInt(String::length).reversed().thenComparing(Comparator.naturalOrder()));
        boolean[] taken = new boolean[haystack.length()];
        record Hit(int at, String key) { }
        List<Hit> hits = new ArrayList<>();
        for (String key : keys) {
            int from = 0;
            while (true) {
                int at = haystack.indexOf(key, from);
                if (at < 0) break;
                boolean free = true;
                for (int i = at; i < at + key.length(); i++) free &= !taken[i];
                if (free) {
                    Arrays.fill(taken, at, at + key.length(), true);
                    hits.add(new Hit(at, key));
                }
                from = at + 1;
            }
        }
        hits.sort(Comparator.comparingInt(Hit::at));
        // One mention per set of companies: two aliases of the same company name it once.
        Map<List<String>, Mention> mentions = new LinkedHashMap<>();
        for (Hit hit : hits) {
            List<String> ids = byKey.get(hit.key()).stream().map(Company::id).sorted().toList();
            mentions.putIfAbsent(ids, new Mention(text.substring(hit.at(), hit.at() + hit.key().length()),
                    List.copyOf(byKey.get(hit.key()))));
        }
        return List.copyOf(mentions.values());
    }
}
