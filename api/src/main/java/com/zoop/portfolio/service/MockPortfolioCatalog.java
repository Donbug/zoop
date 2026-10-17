package com.zoop.portfolio.service;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.portfolio.model.MockCash;
import com.zoop.portfolio.model.MockHolding;
import com.zoop.portfolio.model.MockPortfolio;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

/** Immutable, synthetic demonstration portfolios. This catalog never reads brokerage credentials or live accounts. */
@Component
public class MockPortfolioCatalog {
    private final List<MockPortfolio> portfolios;
    private final String fingerprint;

    public MockPortfolioCatalog(ObjectMapper mapper) {
        try (var input = new ClassPathResource("portfolio/mock-portfolios.json").getInputStream()) {
            JsonNode root = mapper.readTree(input);
            fingerprint = fingerprint(root.toString());
            if (!"synthetic-project-fixture".equals(root.path("source").asText())) {
                throw new IllegalStateException("Mock portfolio data must be identified as synthetic");
            }
            Instant asOf = Instant.parse(root.path("asOf").asText());
            var parsed = new ArrayList<MockPortfolio>();
            var ids = new HashSet<String>();
            for (JsonNode item : root.path("profiles")) {
                String id = requiredText(item, "id");
                if (!ids.add(id)) throw new IllegalStateException("Duplicate mock portfolio id: " + id);
                var holdings = new ArrayList<MockHolding>();
                for (JsonNode holding : item.path("holdings")) {
                    var quantity = decimal(holding, "quantity");
                    var avgPrice = decimal(holding, "avgPrice");
                    if (quantity.signum() <= 0 || avgPrice.signum() < 0) {
                        throw new IllegalStateException("Invalid mock holding quantity or average price");
                    }
                    holdings.add(new MockHolding(requiredText(holding, "companyId"), requiredText(holding, "name"),
                            requiredText(holding, "ticker"), quantity, avgPrice,
                            requiredText(holding, "avgPriceCurrency")));
                }
                JsonNode cashNode = item.path("cash");
                MockCash cash = null;
                if (!cashNode.isMissingNode() && !cashNode.isNull()) {
                    BigDecimal amount = decimal(cashNode, "amount");
                    if (amount.signum() < 0) throw new IllegalStateException("Mock cash amount cannot be negative");
                    cash = new MockCash(amount, requiredText(cashNode, "currency"));
                }
                parsed.add(new MockPortfolio(id, requiredText(item, "label"), requiredText(item, "accountId"),
                        cash, asOf, holdings));
            }
            if (parsed.isEmpty()) throw new IllegalStateException("At least one mock portfolio is required");
            portfolios = List.copyOf(parsed);
        } catch (IOException | RuntimeException exception) {
            throw new IllegalStateException("Unable to load the fixed mock portfolio catalog", exception);
        }
    }

    public List<MockPortfolio> all() {
        return portfolios;
    }

    public Optional<MockPortfolio> find(String id) {
        return portfolios.stream().filter(portfolio -> portfolio.id().equals(id)).findFirst();
    }

    public Page page(String cursor, Integer requestedLimit) {
        if (requestedLimit != null && requestedLimit < 1) throw new CustomException(ErrorCode.INVALID_REQUEST);
        int offset = 0;
        int limit = requestedLimit == null ? Math.max(1, portfolios.size()) : requestedLimit;
        if (cursor != null) {
            Cursor decoded = decode(cursor, fingerprint);
            if (requestedLimit != null && requestedLimit != decoded.limit()) {
                throw new CustomException(ErrorCode.INVALID_CURSOR);
            }
            offset = decoded.offset();
            limit = decoded.limit();
        }
        if (offset >= portfolios.size() && offset != 0) throw new CustomException(ErrorCode.INVALID_CURSOR);
        int end = (int) Math.min(portfolios.size(), (long) offset + limit);
        String nextCursor = end < portfolios.size() ? encode(end, limit, fingerprint) : null;
        return new Page(portfolios.subList(offset, end), nextCursor);
    }

    private static Cursor decode(String cursor, String fingerprint) {
        try {
            if (cursor.length() > 128) throw new IllegalArgumentException();
            String decoded = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.US_ASCII);
            String[] parts = decoded.split(":", -1);
            if (parts.length != 4 || !"v1".equals(parts[0]) || !fingerprint.equals(parts[1])) {
                throw new IllegalArgumentException();
            }
            int offset = Integer.parseInt(parts[2]);
            int limit = Integer.parseInt(parts[3]);
            if (offset < 1 || limit < 1) {
                throw new IllegalArgumentException();
            }
            return new Cursor(offset, limit);
        } catch (RuntimeException exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR);
        }
    }

    private static String encode(int offset, int limit, String fingerprint) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(
                ("v1:" + fingerprint + ":" + offset + ":" + limit).getBytes(StandardCharsets.US_ASCII));
    }

    private static String fingerprint(String content) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(content.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private static String requiredText(JsonNode node, String field) {
        JsonNode value = node.path(field);
        if (!value.isTextual() || value.textValue().isBlank()) {
            throw new IllegalStateException("Mock portfolio field is missing: " + field);
        }
        return value.textValue();
    }

    private static BigDecimal decimal(JsonNode node, String field) {
        JsonNode value = node.path(field);
        if (!value.isNumber()) throw new IllegalStateException("Mock portfolio numeric field is missing: " + field);
        return value.decimalValue();
    }

    private record Cursor(int offset, int limit) { }

    public record Page(List<MockPortfolio> items, String nextCursor) {
        public Page {
            items = List.copyOf(items);
        }
    }
}
