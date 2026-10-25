package com.zoop.company.catalog;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Array;
import java.sql.SQLException;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.regex.Pattern;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Explicit development catalog import. The prototype is never read at runtime. */
@Service
public class CompanyCatalogImportService {
    private static final Pattern BRAND_COLOR = Pattern.compile("#[0-9A-Fa-f]{6}");
    private static final Pattern LOGO_FILE = Pattern.compile("[a-z0-9]+(?:-[a-z0-9]+)*\\.svg");
    private static final Set<String> EXCHANGES = Set.of("KRX", "NASDAQ", "NYSE", "TSE");
    private static final Set<String> PROFILE_KEYS = Set.of("legalName", "representative", "foundedDate", "websiteUrl",
            "sector", "businessSummary");
    /** The chatbot cites a business summary as one quote, so it stays well within the quote limit. */
    private static final int MAX_BUSINESS_SUMMARY = 600;
    private static final Pattern WEBSITE = Pattern.compile("https://[^\\s]+");
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public CompanyCatalogImportService(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    @Transactional
    public ImportResult importFile(Path path) {
        try {
            return importCatalog(read(mapper.readTree(Files.readString(path))));
        } catch (IOException | JacksonException exception) {
            throw new IllegalArgumentException("Cannot read company catalog: " + path, exception);
        }
    }

    @Transactional
    public ImportResult importResource(Resource resource) {
        try (InputStream stream = resource.getInputStream()) {
            return importCatalog(read(mapper.readTree(stream)));
        } catch (IOException | JacksonException exception) {
            throw new IllegalArgumentException("Cannot read company catalog resource", exception);
        }
    }

    private ImportResult importCatalog(List<CompanySeed> companies) {
        // Keep the comparison and writes in one transaction, without racing another catalog writer.
        jdbc.execute("LOCK TABLE companies IN SHARE ROW EXCLUSIVE MODE");
        int changed = 0;
        for (CompanySeed company : companies) {
            List<CompanySeed> existing = jdbc.query("""
                    SELECT id, name, ticker, exchange_code, aliases, brand_color, logo_url, market, brand_source,
                           profile::text AS profile
                    FROM companies WHERE id = ?
                    """, (rs, row) -> new CompanySeed(rs.getString("id"), rs.getString("name"),
                    rs.getString("ticker"), rs.getString("exchange_code"), sqlAliases(rs.getArray("aliases")),
                    rs.getString("brand_color"), rs.getString("logo_url"), rs.getString("market"),
                    rs.getString("brand_source"), true, true, mapper.readTree(rs.getString("profile"))),
                    company.id());
            String market = company.id().equals("ORG:OPENAI") || company.id().equals("ORG:ANTHROPIC")
                    ? null : company.marketProvided() ? company.market()
                    : existing.isEmpty() ? null : existing.getFirst().market();
            JsonNode profile = company.profile() != null ? company.profile()
                    : existing.isEmpty() ? mapper.createObjectNode() : existing.getFirst().profile();
            String logoUrl = company.logoUrl() != null ? company.logoUrl()
                    : existing.isEmpty() ? null : existing.getFirst().logoUrl();
            String brandSource = company.brandSourceProvided() ? company.brandSource()
                    : existing.isEmpty() ? null : existing.getFirst().brandSource();
            CompanySeed desired = new CompanySeed(company.id(), company.name(), company.ticker(),
                    company.exchangeCode(), company.aliases(), company.brandColor(), logoUrl, market,
                    brandSource, true, true, profile);
            if (existing.size() == 1 && existing.getFirst().equals(desired)) {
                continue;
            }
            jdbc.update(connection -> {
                var statement = connection.prepareStatement("""
                        INSERT INTO companies (id, name, ticker, exchange_code, aliases, brand_color, logo_url,
                                               market, brand_source, profile)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS jsonb))
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            ticker = EXCLUDED.ticker,
                            exchange_code = EXCLUDED.exchange_code,
                            aliases = EXCLUDED.aliases,
                            brand_color = EXCLUDED.brand_color,
                            logo_url = EXCLUDED.logo_url,
                            market = EXCLUDED.market,
                            brand_source = EXCLUDED.brand_source,
                            profile = EXCLUDED.profile
                        """);
                statement.setString(1, company.id());
                statement.setString(2, company.name());
                statement.setString(3, company.ticker());
                statement.setString(4, company.exchangeCode());
                statement.setArray(5, connection.createArrayOf("text", company.aliases().toArray(String[]::new)));
                statement.setString(6, company.brandColor());
                statement.setString(7, logoUrl);
                statement.setString(8, market);
                statement.setString(9, brandSource);
                statement.setString(10, mapper.writeValueAsString(profile));
                return statement;
            });
            changed++;
        }
        return new ImportResult(companies.size(), changed, companies.size() - changed);
    }

    private static List<String> sqlAliases(Array value) throws SQLException {
        return List.of((String[]) value.getArray());
    }

    private List<CompanySeed> read(JsonNode root) {
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
            String logo = optionalText(item, "logo");
            if (logo != null && !LOGO_FILE.matcher(logo).matches()) {
                throw new IllegalArgumentException("Invalid logo filename for " + id);
            }
            String logoUrl = logo == null ? null : "/graph-assets/" + logo;
            String brandSource = optionalText(item, "brand_source");
            String market = optionalText(item, "market");
            if (market != null && ticker == null) {
                throw new IllegalArgumentException("market requires a listed company: " + id);
            }
            companies.add(new CompanySeed(id, name, ticker, exchangeCode, List.copyOf(aliases), brandColor,
                    logoUrl, market, brandSource, item.has("brand_source"), item.has("market"),
                    item.has("profile") ? profile(item.get("profile"), id) : null));
        }
        return List.copyOf(companies);
    }

    /** Only the keys the company detail reads (others are rejected); a null value is left out so the API reports it as null. */
    private ObjectNode profile(JsonNode node, String id) {
        if (node.isNull()) {
            return mapper.createObjectNode(); // explicit null clears, like market and brand_source
        }
        if (!node.isObject()) {
            throw new IllegalArgumentException("profile must be an object for " + id);
        }
        ObjectNode profile = mapper.createObjectNode();
        for (String key : node.propertyNames()) {
            if (!PROFILE_KEYS.contains(key)) {
                throw new IllegalArgumentException("Unknown profile key " + key + " for " + id);
            }
            String value = optionalText(node, key);
            if (value == null) {
                continue;
            }
            if (key.equals("foundedDate")) {
                try {
                    LocalDate.parse(value);
                } catch (DateTimeParseException exception) {
                    throw new IllegalArgumentException("foundedDate must be YYYY-MM-DD for " + id, exception);
                }
            }
            if (key.equals("websiteUrl") && !WEBSITE.matcher(value).matches()) {
                throw new IllegalArgumentException("websiteUrl must be an https URL for " + id);
            }
            if (key.equals("businessSummary") && value.codePointCount(0, value.length()) > MAX_BUSINESS_SUMMARY) {
                throw new IllegalArgumentException("businessSummary must be at most " + MAX_BUSINESS_SUMMARY
                        + " characters for " + id);
            }
            profile.put(key, value);
        }
        return profile;
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
                               List<String> aliases, String brandColor, String logoUrl, String market,
                               String brandSource, boolean brandSourceProvided, boolean marketProvided,
                               JsonNode profile) {
    }

    public record ImportResult(int total, int changed, int unchanged) {
    }
}
