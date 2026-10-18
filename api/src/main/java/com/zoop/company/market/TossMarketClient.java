package com.zoop.company.market;

import java.net.URI;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.locks.ReentrantLock;

import com.zoop.company.market.dto.CompanyPriceResponse;
import com.zoop.company.market.dto.CompanyQuoteResponse;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Component
public class TossMarketClient {
    private static final String AUTH_FAILED = "토스증권 인증에 실패했어요. 시세 키를 확인해 주세요.";
    private static final String FORMAT_CHANGED = "토스증권 응답 형식을 읽지 못했어요.";
    private static final String TEMPORARY = "시세 출처에 잠시 연결하지 못했어요. 잠시 후 다시 시도해 주세요.";
    private final CompanyMarketSettings settings;
    private final RestClient client;
    private final ObjectMapper mapper;
    private final Clock clock;
    private final ReentrantLock tokenLock = new ReentrantLock();
    private volatile String token;
    private volatile Instant tokenExpires = Instant.EPOCH;

    public TossMarketClient(CompanyMarketSettings settings, ObjectMapper mapper, Clock clock) {
        this.settings = settings;
        this.mapper = mapper;
        this.clock = clock;
        var httpClient = java.net.http.HttpClient.newBuilder().connectTimeout(settings.timeout()).build();
        var requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(settings.timeout());
        this.client = RestClient.builder().baseUrl(settings.tossBaseUrl()).requestFactory(requestFactory).build();
    }

    public CompanyQuoteResponse quote(String companyId, String exchange, String code) {
        if (!"toss".equalsIgnoreCase(settings.quoteProvider())
                || blank(settings.tossClientId()) || blank(settings.tossClientSecret())) {
            return CompanyQuoteResponse.unavailable(companyId, "not_connected", "토스증권 시세 키가 설정되지 않았어요.");
        }
        if (!("KRX".equals(exchange) || "NASDAQ".equals(exchange) || "NYSE".equals(exchange) || "AMEX".equals(exchange))) {
            return CompanyQuoteResponse.unavailable(companyId, "unsupported_symbol", "이 종목은 토스증권 시세 조회를 지원하지 않아요.");
        }
        try {
            JsonNode priceRoot = get("/api/v1/prices", Map.of("symbols", code));
            JsonNode price = matching(priceRoot.path("result"), code);
            if (price == null) return CompanyQuoteResponse.unavailable(companyId, "unsupported_symbol", "토스증권에서 이 종목을 찾지 못했어요.");
            // Absent values are a normal "no data"; a present value in the wrong shape is a provider format failure.
            Double last = strictNumber(price.get("lastPrice"));
            String currency = strictText(price.get("currency"));
            if (last == null || currency == null) {
                return CompanyQuoteResponse.unavailable(companyId, "no_data", "토스증권에 현재가 또는 통화 정보가 없어요.");
            }
            // A missing observation time keeps the price with quote.asOf = null; an unreadable one is a format failure.
            String timestamp = strictText(price.get("timestamp"));
            Instant asOf = timestamp == null ? null : instant(timestamp);
            if (timestamp != null && asOf == null) throw formatFailure();
            JsonNode stocks = get("/api/v1/stocks", Map.of("symbols", code));
            JsonNode stock = matching(stocks.path("result"), code);
            Double shares = stock == null ? null : number(stock.get("sharesOutstanding"));
            List<JsonNode> daily = dailyCandles(code, 3, null);
            // Daily candles are dated in the market's own calendar, so the quote's session day uses the same zone.
            String sessionDate = asOf == null ? null : asOf.atZone(marketZone(exchange)).toLocalDate().toString();
            // The 52-week range only uses candles from the year ending on the quote's session date.
            String windowStart = sessionDate == null ? null
                    : java.time.LocalDate.parse(sessionDate).minusDays(365).toString();
            JsonNode current = null, previous = null;
            Double high52 = null, low52 = null;
            String oldestDate = null;
            for (JsonNode candle : daily) {
                String day = text(candle.get("timestamp"));
                if (day == null || !day.matches("\\d{4}-\\d{2}-\\d{2}.*")) continue;
                day = day.substring(0, 10);
                if (oldestDate == null || day.compareTo(oldestDate) < 0) oldestDate = day;
                if (sessionDate != null && day.equals(sessionDate)) current = candle;
                if (sessionDate != null && day.compareTo(sessionDate) < 0 && (previous == null
                        || day.compareTo(text(previous.get("timestamp")).substring(0, 10)) > 0)) previous = candle;
                if (windowStart == null || day.compareTo(windowStart) < 0 || day.compareTo(sessionDate) > 0) continue;
                Double high = number(candle.get("highPrice")), low = number(candle.get("lowPrice"));
                if (high != null) high52 = high52 == null ? high : Math.max(high52, high);
                if (low != null) low52 = low52 == null ? low : Math.min(low52, low);
            }
            if (sessionDate == null || oldestDate == null
                    || java.time.LocalDate.parse(oldestDate).isAfter(java.time.LocalDate.parse(sessionDate).minusDays(365))) {
                high52 = null; low52 = null;
            }
            Double previousClose = previous == null ? null : number(previous.get("closePrice"));
            Double change = previousClose == null ? null : last - previousClose;
            Double changeRate = previousClose == null || previousClose == 0 ? null : change / previousClose;
            Double marketCap = shares == null ? null : shares * last;
            List<String> derived = new java.util.ArrayList<>();
            if (previousClose != null) derived.addAll(List.of("previousClose", "change", "changeRate"));
            if (high52 != null && low52 != null) derived.addAll(List.of("fiftyTwoWeekHigh", "fiftyTwoWeekLow"));
            if (marketCap != null) derived.add("marketCap");
            var quote = new CompanyQuoteResponse.QuoteValues(currency, last, asOf, previousClose, change, changeRate,
                    current == null ? null : number(current.get("highPrice")),
                    current == null ? null : number(current.get("lowPrice")),
                    current == null ? null : number(current.get("volume")), high52, low52, marketCap, shares, derived);
            return CompanyQuoteResponse.available(companyId,
                    new CompanyQuoteResponse.Source("toss", "토스증권", true, null, code, null), quote);
        } catch (MarketDataException exception) {
            throw exception;
        } catch (TossUnsupportedSymbolException exception) {
            return CompanyQuoteResponse.unavailable(companyId, "unsupported_symbol", "토스증권에서 이 종목을 찾지 못했어요.");
        } catch (RestClientException exception) {
            throw new MarketDataException(true);
        } catch (Exception exception) {
            throw new MarketDataException(false);
        }
    }

    /** Bar resolution the contract fixes per period: 1d=5m, 1w=1h, 1m=1d, 1y=1wk. */
    public static final Map<String, String> PERIOD_INTERVAL = Map.of("1d", "5m", "1w", "1h", "1m", "1d", "1y", "1wk");
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");

    /**
     * getCompanyPrices. Toss serves only 1-minute and daily candles, so only 1m (daily bars) can be answered; the other
     * periods are a normal no_data rather than bars re-labelled, aggregated or interpolated from another resolution
     * (contract). The range is in KST calendar days: fromDay defaults to one month back from today (prototype
     * {@code period_start}), toDay to no upper bound.
     */
    public CompanyPriceResponse prices(String companyId, String exchange, String code, String period,
            LocalDate fromDay, LocalDate toDay) {
        if (!"toss".equalsIgnoreCase(settings.quoteProvider())
                || blank(settings.tossClientId()) || blank(settings.tossClientSecret())) {
            return CompanyPriceResponse.unavailable(companyId, period, "not_connected", "토스증권 시세 키가 설정되지 않았어요.");
        }
        if (!("KRX".equals(exchange) || "NASDAQ".equals(exchange) || "NYSE".equals(exchange) || "AMEX".equals(exchange))) {
            return CompanyPriceResponse.unavailable(companyId, period, "unsupported_symbol", "이 종목은 토스증권 시세 조회를 지원하지 않아요.");
        }
        String interval = PERIOD_INTERVAL.get(period);
        if (!"1d".equals(interval)) {
            return CompanyPriceResponse.unavailable(companyId, period, "no_data",
                    "연결한 시세 출처(토스증권)는 " + interval + " 간격 가격 자료를 제공하지 않아요.");
        }
        LocalDate cutoff = fromDay != null ? fromDay : LocalDate.now(clock.withZone(KST)).minusMonths(1);
        try {
            List<CompanyPriceResponse.Point> points = new java.util.ArrayList<>();
            for (JsonNode candle : dailyCandles(code, 10, cutoff)) {
                Instant at = instant(text(candle.get("timestamp")));
                if (at == null) continue;
                LocalDate day = at.atZone(KST).toLocalDate();
                if (day.isBefore(cutoff) || (toDay != null && day.isAfter(toDay))) continue;
                Double open = number(candle.get("openPrice")), high = number(candle.get("highPrice"));
                Double low = number(candle.get("lowPrice")), close = number(candle.get("closePrice"));
                if (open == null || high == null || low == null || close == null) continue;
                String time = at.atZone(marketZone(exchange)).toOffsetDateTime().toString();
                points.add(new CompanyPriceResponse.Point(time, open, high, low, close, number(candle.get("volume"))));
            }
            if (points.isEmpty()) {
                return CompanyPriceResponse.unavailable(companyId, period, "no_data", "이 기간에는 거래된 시세가 없어요(휴장일 등).");
            }
            points.sort(java.util.Comparator.comparing(point -> java.time.OffsetDateTime.parse(point.time())));
            JsonNode stock = matching(get("/api/v1/stocks", Map.of("symbols", code)).path("result"), code);
            String currency = stock == null ? null : strictText(stock.get("currency"));
            if (currency == null) {
                return CompanyPriceResponse.unavailable(companyId, period, "no_data", "토스증권 응답에 통화가 없어요.");
            }
            return CompanyPriceResponse.available(companyId, period,
                    new CompanyQuoteResponse.Source("toss", "토스증권", true, null, code, null), currency, interval, points);
        } catch (MarketDataException exception) {
            throw exception;
        } catch (TossUnsupportedSymbolException exception) {
            return CompanyPriceResponse.unavailable(companyId, period, "unsupported_symbol", "토스증권에서 이 종목을 찾지 못했어요.");
        } catch (RestClientException exception) {
            throw new MarketDataException(true);
        } catch (Exception exception) {
            throw new MarketDataException(false);
        }
    }

    /** Daily candles newest first, following nextBefore for up to maxPages pages or until a page ends before stopBefore (KST day). */
    private List<JsonNode> dailyCandles(String code, int maxPages, LocalDate stopBefore) {
        List<JsonNode> daily = new java.util.ArrayList<>();
        String before = null;
        for (int page = 0; page < maxPages; page++) {
            var candleParams = new java.util.HashMap<String, Object>();
            candleParams.put("symbol", code); candleParams.put("interval", "1d"); candleParams.put("count", "200");
            if (before != null) candleParams.put("before", before);
            JsonNode candlePage = get("/api/v1/candles", candleParams).path("result");
            JsonNode candles = candlePage.path("candles");
            if (!candles.isArray()) throw formatFailure();
            candles.forEach(daily::add);
            if (candles.isEmpty() || !candlePage.hasNonNull("nextBefore")) break;
            Instant oldest = instant(text(candles.get(candles.size() - 1).get("timestamp")));
            if (stopBefore != null && oldest != null && oldest.atZone(KST).toLocalDate().isBefore(stopBefore)) break;
            before = text(candlePage.get("nextBefore"));
        }
        return daily;
    }

    private JsonNode get(String path, Map<String, ?> params) {
        String accessToken = token();
        for (int attempt = 0; attempt < 2; attempt++) {
            final String usedToken = accessToken;
            final boolean firstAttempt = attempt == 0;
            var response = client.get().uri(uri -> {
                var builder = uri.path(path);
                // Values go through URI variables so reserved characters are encoded ("+09:00" -> "%2B09:00");
                // a literal "+" would otherwise reach the provider as a space.
                params.keySet().forEach(key -> builder.queryParam(key, "{" + key + "}"));
                return builder.build(params);
            }).header("Authorization", "Bearer " + usedToken).accept(MediaType.APPLICATION_JSON)
                    .exchange((request, result) -> {
                        int code = result.getStatusCode().value();
                        byte[] body = result.getBody().readAllBytes();
                        if (code == 401 && firstAttempt) return new HttpResult(code, body);
                        if (code == 401 || code == 403) throw new MarketDataException(false);
                        if (code == 400 || code == 404) throw new TossUnsupportedSymbolException();
                        if (code == 429 || code >= 500) throw new MarketDataException(true);
                        if (code < 200 || code >= 300) throw new MarketDataException(false);
                        return new HttpResult(code, body);
                    });
            if (response.status == 401 && attempt == 0) { accessToken = token(usedToken); continue; }
            JsonNode root = read(response.body);
            if (!root.isObject() || !root.has("result")) throw formatFailure();
            return root;
        }
        throw new MarketDataException(false);
    }

    private String token() { return token(null); }
    private String token(String stale) {
        if (token != null && Instant.now().isBefore(tokenExpires) && !token.equals(stale)) return token;
        tokenLock.lock();
        try {
            if (token != null && Instant.now().isBefore(tokenExpires) && !token.equals(stale)) return token;
            var form = new LinkedMultiValueMap<String, String>();
            form.add("grant_type", "client_credentials");
            form.add("client_id", settings.tossClientId());
            form.add("client_secret", settings.tossClientSecret());
            JsonNode root;
            try {
                byte[] body = client.post().uri("/oauth2/token").contentType(MediaType.APPLICATION_FORM_URLENCODED)
                        .body(form).exchange((request, response) -> {
                            int code = response.getStatusCode().value();
                            byte[] bytes = response.getBody().readAllBytes();
                            if (code == 400 || code == 401 || code == 403) throw new TossAuthException();
                            if (code == 429 || code >= 500) throw new MarketDataException(true);
                            if (code < 200 || code >= 300) throw new MarketDataException(false);
                            return bytes;
                        });
                root = read(body);
            } catch (TossAuthException exception) { throw new MarketDataException(false); }
            catch (RestClientException exception) { throw new MarketDataException(true); }
            String newToken = text(root.get("access_token"));
            Double expires = number(root.get("expires_in"));
            if (newToken == null || expires == null || expires <= 0) throw formatFailure();
            token = newToken;
            long expiresSeconds = expires.longValue();
            tokenExpires = Instant.now().plusSeconds(Math.max(1, expiresSeconds - Math.min(60, expiresSeconds / 2)));
            return token;
        } finally { tokenLock.unlock(); }
    }

    private JsonNode read(byte[] bytes) {
        try { return mapper.readTree(bytes); }
        catch (Exception exception) { throw formatFailure(); }
    }
    private static JsonNode matching(JsonNode rows, String symbol) {
        if (rows == null || rows.isNull()) return null;
        if (!rows.isArray()) throw formatFailure();
        for (JsonNode row : rows) if (symbol.equalsIgnoreCase(text(row.get("symbol")))) return row;
        return null;
    }
    private static String text(JsonNode node) { return node == null || node.isNull() || !node.isString() ? null : node.stringValue(); }
    private static Double number(JsonNode node) {
        if (node == null || node.isNull()) return null;
        try { double value = node.isNumber() ? node.doubleValue() : node.isString() ? Double.parseDouble(node.stringValue()) : Double.NaN;
            return Double.isFinite(value) ? value : null; } catch (NumberFormatException ignored) { return null; }
    }
    private static java.time.ZoneId marketZone(String exchange) {
        return java.time.ZoneId.of("KRX".equals(exchange) ? "Asia/Seoul" : "America/New_York");
    }
    private static Double strictNumber(JsonNode node) {
        if (node == null || node.isNull()) return null;
        Double value = number(node);
        if (value == null) throw formatFailure();
        return value;
    }
    private static String strictText(JsonNode node) {
        if (node == null || node.isNull()) return null;
        if (!node.isString()) throw formatFailure();
        return node.stringValue().isBlank() ? null : node.stringValue();
    }
    private static Instant instant(String value) {
        if (value == null) return null;
        try { return java.time.OffsetDateTime.parse(value).toInstant(); }
        catch (Exception ignored) { try { return java.time.LocalDateTime.parse(value).atZone(java.time.ZoneId.of("Asia/Seoul")).toInstant(); }
            catch (Exception ignoredAgain) { return null; } }
    }
    private static boolean blank(String value) { return value == null || value.isBlank(); }
    private static MarketDataException formatFailure() { return new MarketDataException(false); }
    private record HttpResult(int status, byte[] body) { }
    private static class TossAuthException extends RuntimeException { }
    private static class TossUnsupportedSymbolException extends RuntimeException { }
}
