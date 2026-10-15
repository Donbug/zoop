package com.zoop.company.catalog;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Array;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.regex.Pattern;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Explicit development catalog import. The prototype is never read at runtime. */
@Service
public class CompanyCatalogImportService {
    private static final Pattern BRAND_COLOR = Pattern.compile("#[0-9A-Fa-f]{6}");
    private static final Set<String> EXCHANGES = Set.of("KRX", "NASDAQ", "NYSE", "TSE");
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public CompanyCatalogImportService(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    @Transactional
    public ImportResult importFile(Path path) {
        List<CompanySeed> companies = read(path);
        // Keep the comparison and writes in one transaction, without racing another catalog writer.
        jdbc.execute("LOCK TABLE companies IN SHARE ROW EXCLUSIVE MODE");
        int changed = 0;
        for (CompanySeed company : companies) {
            List<CompanySeed> existing = jdbc.query("""
                    SELECT id, name, ticker, exchange_code, aliases, brand_color
                    FROM companies WHERE id = ?
                    """, (rs, row) -> new CompanySeed(rs.getString("id"), rs.getString("name"),
                    rs.getString("ticker"), rs.getString("exchange_code"), sqlAliases(rs.getArray("aliases")),
                    rs.getString("brand_color")), company.id());
            if (existing.size() == 1 && existing.getFirst().equals(company)) {
                continue;
            }
            jdbc.update(connection -> {
                var statement = connection.prepareStatement("""
                        INSERT INTO companies (id, name, ticker, exchange_code, aliases, brand_color)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            ticker = EXCLUDED.ticker,
                            exchange_code = EXCLUDED.exchange_code,
                            aliases = EXCLUDED.aliases,
                            brand_color = EXCLUDED.brand_color
                        """);
                statement.setString(1, company.id());
                statement.setString(2, company.name());
                statement.setString(3, company.ticker());
                statement.setString(4, company.exchangeCode());
                statement.setArray(5, connection.createArrayOf("text", company.aliases().toArray(String[]::new)));
                statement.setString(6, company.brandColor());
                return statement;
            });
            changed++;
        }
        return new ImportResult(companies.size(), changed, companies.size() - changed);
    }

    private static List<String> sqlAliases(Array value) throws SQLException {
        return List.of((String[]) value.getArray());
    }

    private List<CompanySeed> read(Path path) {
        final JsonNode root;
        try {
            root = mapper.readTree(Files.readString(path));
        } catch (IOException | JacksonException exception) {
            throw new IllegalArgumentException("Cannot read company catalog: " + path, exception);
        }
        JsonNode items = root == null ? null : root.get("companies");
        if (items == null || !items.isArray() || items.isEmpty()) {
            throw new IllegalArgumentException("Company catalog must contain a nonempty companies array");
        }
        List<CompanySeed> companies = new ArrayList<>(items.size());
        Set<String> ids = new HashSet<>();
        for (JsonNode item : items) {
            if (!item.isObject()) {
                throw new IllegalArgumentException("Company catalog entries must be objects");
            }
            String id = requiredText(item, "company_id");
            if (!ids.add(id)) {
                throw new IllegalArgumentException("Duplicate company_id: " + id);
            }
            String name = requiredText(item, "name");
            String ticker = optionalText(item, "ticker");
            String exchangeCode = null;
            if (ticker != null) {
                int separator = id.indexOf(':');
                if (separator < 1 || !EXCHANGES.contains(id.substring(0, separator))
                        || !ticker.equals(id.substring(separator + 1))) {
                    throw new IllegalArgumentException("Listed company_id must be EXCHANGE:ticker: " + id);
                }
                exchangeCode = id.substring(0, separator);
            }
            JsonNode aliasesNode = item.get("aliases");
            if (aliasesNode == null || !aliasesNode.isArray()) {
                throw new IllegalArgumentException("aliases must be an array for " + id);
            }
            List<String> aliases = new ArrayList<>(aliasesNode.size());
            for (JsonNode alias : aliasesNode) {
                if (!alias.isTextual() || alias.textValue().isBlank()) {
                    throw new IllegalArgumentException("aliases must contain nonblank strings for " + id);
                }
                aliases.add(alias.textValue());
            }
            String brandColor = optionalText(item, "brand_color");
            if (brandColor != null && !BRAND_COLOR.matcher(brandColor).matches()) {
                throw new IllegalArgumentException("Invalid brand_color for " + id);
            }
            companies.add(new CompanySeed(id, name, ticker, exchangeCode, List.copyOf(aliases), brandColor));
        }
        return List.copyOf(companies);
    }

    private static String requiredText(JsonNode item, String field) {
        String value = optionalText(item, field);
        if (value == null) {
            throw new IllegalArgumentException(field + " must be a nonblank string");
        }
        return value;
    }

    private static String optionalText(JsonNode item, String field) {
        JsonNode value = item.get(field);
        if (value == null || value.isNull()) {
            return null;
        }
        if (!value.isTextual() || value.textValue().isBlank()
                || !Objects.equals(value.textValue(), value.textValue().strip())) {
            throw new IllegalArgumentException(field + " must be a nonblank trimmed string or null");
        }
        return value.textValue();
    }

    private record CompanySeed(String id, String name, String ticker, String exchangeCode,
                               List<String> aliases, String brandColor) {
    }

    public record ImportResult(int total, int changed, int unchanged) {
    }
}
