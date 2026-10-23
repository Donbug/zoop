package com.zoop.company.market;

import java.net.URI;
import java.time.Instant;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.zoop.company.market.dto.CompanyMetricsResponse;
import com.zoop.company.market.dto.CompanyQuoteResponse;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Component
public class NaverMetricsClient {
    private static final Map<String, String> LABELS = Map.ofEntries(Map.entry("marketValue", "시가총액"),
            Map.entry("per", "PER"), Map.entry("eps", "EPS"), Map.entry("pbr", "PBR"),
            Map.entry("bps", "BPS"), Map.entry("dividendYieldRatio", "배당수익률"),
            Map.entry("dividend", "주당배당금"), Map.entry("foreignRate", "외국인 소진율"));
    private final CompanyMarketSettings settings;
    private final RestClient domestic;
    private final RestClient world;
    private final RestClient autocomplete;
    private final ObjectMapper mapper;
    private final MarketDataCache<String, CompanyMetricsResponse> metricsCache;
    private final MarketDataConcurrencyLimiter limiter;

    public NaverMetricsClient(CompanyMarketSettings settings, ObjectMapper mapper) {
        this.settings = settings; this.mapper = mapper;
        this.metricsCache = new MarketDataCache<>(settings.cacheMaxEntries());
        this.limiter = new MarketDataConcurrencyLimiter(settings.providerMaxConcurrentRequests(), settings.timeout());
        var httpClient = java.net.http.HttpClient.newBuilder().connectTimeout(settings.timeout()).build();
        var requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(settings.timeout());
        this.domestic = RestClient.builder().baseUrl(settings.naverDomesticUrl()).requestFactory(requestFactory).defaultHeader("User-Agent", "Mozilla/5.0").build();
        this.world = RestClient.builder().baseUrl(settings.naverWorldUrl()).requestFactory(requestFactory).defaultHeader("User-Agent", "Mozilla/5.0").build();
        this.autocomplete = RestClient.builder().baseUrl(settings.naverAutocompleteUrl()).requestFactory(requestFactory).defaultHeader("User-Agent", "Mozilla/5.0").build();
    }

    public CompanyMetricsResponse metrics(String id, String exchange, String code) {
        if (!"naver".equalsIgnoreCase(settings.metricsProvider())) return CompanyMetricsResponse.unavailable(id, "not_connected", "지표 출처를 연결하지 않았어요.");
        boolean krx = "KRX".equals(exchange) && code.matches("[0-9A-Z]{6}");
        boolean supported = krx || (List.of("NASDAQ", "NYSE", "AMEX").contains(exchange) && code.matches("[A-Z][A-Z0-9.\\-]{0,9}"))
                || ("TSE".equals(exchange) && code.matches("[0-9A-Z]{4}"));
        if (!supported) return CompanyMetricsResponse.unavailable(id, "unsupported_symbol", "이 종목은 지표 출처에서 제공하지 않아요.");
        String key = id + "|" + exchange + "|" + code;
        return metricsCache.get(key, () -> loadMetrics(id, exchange, code), result ->
                "available".equals(result.status()) ? settings.metricsCacheTtl()
                        : shorter(settings.metricsCacheTtl(), Duration.ofMinutes(1)));
    }

    private CompanyMetricsResponse loadMetrics(String id, String exchange, String code) {
        boolean krx = "KRX".equals(exchange) && code.matches("[0-9A-Z]{6}");
        try {
            JsonNode items;
            JsonNode basic;
            String symbol;
            String url;
            String basisKey;
            if (krx) {
                JsonNode integration = fetch(domestic, "/api/stock/" + code + "/integration", Map.of());
                items = integration.get("totalInfos");
                basic = fetch(domestic, "/api/stock/" + code + "/basic", Map.of());
                symbol = code; url = "https://m.stock.naver.com/domestic/stock/" + code + "/total"; basisKey = "valueDesc";
            } else {
                String reuters = resolve(code, exchange);
                basic = fetch(world, "/stock/" + reuters + "/basic", Map.of());
                items = basic.get("stockItemTotalInfos");
                symbol = reuters; url = "https://m.stock.naver.com/worldstock/stock/" + reuters + "/total"; basisKey = "keyDesc";
            }
            if (items == null || !items.isArray()) throw new MarketDataException(false);
            List<CompanyMetricsResponse.Metric> mapped = new ArrayList<>();
            java.util.Set<String> recognized = new java.util.HashSet<>();
            for (JsonNode row : items) {
                String codeValue = string(row.get("code"));
                if (!LABELS.containsKey(codeValue)) continue;
                recognized.add(codeValue);
                String value = string(row.get("value"));
                if (value == null || value.isBlank() || value.equalsIgnoreCase("N/A") || value.equals("-")) continue;
                mapped.add(new CompanyMetricsResponse.Metric(codeValue, LABELS.get(codeValue), value.strip(), string(row.get(basisKey))));
            }
            if (!items.isEmpty() && recognized.isEmpty()) throw new MarketDataException(false);
            if (mapped.isEmpty()) return CompanyMetricsResponse.unavailable(id, "no_data", "네이버 증권에 이 종목의 지표 값이 없어요.");
            Instant asOf = time(string(basic.get("localTradedAt")));
            return CompanyMetricsResponse.available(id, new CompanyQuoteResponse.Source("naver", "네이버 증권", false,
                    "비공식 공개 자료예요. 지연되거나 바뀔 수 있어요.", symbol, url), asOf, mapped);
        } catch (MarketDataException exception) { throw exception; }
        catch (RestClientException exception) { throw new MarketDataException(true); }
        catch (Exception exception) { throw new MarketDataException(false); }
    }

    private String resolve(String code, String exchange) {
        JsonNode root = fetch(autocomplete, "/ac", Map.of("q", code, "target", "stock"));
        JsonNode rows = root.get("items");
        if (rows == null || !rows.isArray()) throw new MarketDataException(false);
        String type = "TSE".equals(exchange) ? "TOKYO" : exchange;
        for (JsonNode row : rows) if (code.equalsIgnoreCase(string(row.get("code"))) && type.equals(string(row.get("typeCode")))) {
            String reuters = string(row.get("reutersCode")); if (reuters != null) return reuters;
        }
        throw new MarketDataException(false);
    }

    private JsonNode fetch(RestClient client, String path, Map<String, ?> params) {
        byte[] bytes = limiter.execute(() -> client.get().uri(builder -> { builder.path(path); params.forEach(builder::queryParam); return builder.build(); })
                .accept(MediaType.APPLICATION_JSON).exchange((request, response) -> {
                    int status = response.getStatusCode().value();
                    if (status == 404 || status == 400) throw new MarketDataException(false);
                    if (status == 429 || status >= 500) throw new MarketDataException(true);
                    if (status == 401 || status == 403) throw new MarketDataException(false);
                    if (status < 200 || status >= 300) throw new MarketDataException(false);
                    return response.getBody().readAllBytes();
                }));
        try { JsonNode node = mapper.readTree(bytes); if (node == null || !node.isObject()) throw new MarketDataException(false); return node; }
        catch (MarketDataException exception) { throw exception; }
        catch (Exception exception) { throw new MarketDataException(false); }
    }
    private static String string(JsonNode node) { return node == null || node.isNull() || !node.isString() ? null : node.stringValue(); }
    private static Duration shorter(Duration configured, Duration cap) {
        return configured.compareTo(cap) < 0 ? configured : cap;
    }
    private static Instant time(String value) {
        if (value == null) return null;
        try { return OffsetDateTime.parse(value).toInstant(); }
        catch (Exception ignored) { try { return LocalDateTime.parse(value).atZone(ZoneId.of("Asia/Seoul")).toInstant(); } catch (Exception alsoIgnored) { return null; } }
    }
}
