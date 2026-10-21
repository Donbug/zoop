package com.zoop.company.market;

import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

import com.sun.net.httpserver.HttpServer;
import com.zoop.company.market.dto.CompanyPriceResponse;
import com.zoop.company.market.dto.CompanyMetricsResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.*;

class CompanyMarketClientsTest {
    private static final java.time.Clock CLOCK =
            java.time.Clock.fixed(java.time.Instant.parse("2026-10-16T03:00:00Z"), java.time.ZoneOffset.UTC);
    private HttpServer server;
    private java.util.concurrent.ExecutorService executor;
    private final AtomicInteger tokenRequests = new AtomicInteger();
    private volatile int tokenStatus = 200;
    private volatile int providerStatus = 200;
    private volatile boolean omitPriceTimestamp;
    private volatile String priceTimestamp = "2026-10-15T06:30:00Z";
    private volatile String lastPriceJson = "700";
    private volatile boolean paginateCandles;
    private volatile boolean rateLimitOnce;
    private volatile boolean omitStockCurrency;
    /** Daily candles stamped like Toss: KRX at KST midnight, US at New York midnight shown in KST. */
    private volatile boolean exchangeDaily;
    private volatile boolean malformedCandle;
    /** NVDA daily candles around the 2026-03-08 US DST start, stamped at New York midnight shown in KST. */
    private volatile boolean dstDaily;
    /** The calendar stub opens Friday 2026-10-16 (otherwise a holiday). */
    private volatile boolean fridayOpen;
    private final List<String> candleQueries = new java.util.concurrent.CopyOnWriteArrayList<>();

    @BeforeEach
    void startProviderStub() throws IOException {
        server = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0);
        executor = Executors.newCachedThreadPool();
        server.setExecutor(executor);
        server.createContext("/", exchange -> {
            String path = exchange.getRequestURI().getPath();
            // Count before replying: once the client has the response the test may assert immediately.
            if (path.equals("/oauth2/token")) tokenRequests.incrementAndGet();
            int status = path.equals("/oauth2/token") ? tokenStatus : providerStatus;
            if (path.equals("/api/v1/candles") && rateLimitOnce) { rateLimitOnce = false; status = 429; }
            String rawQuery = exchange.getRequestURI().getRawQuery();
            if (path.equals("/api/v1/candles")) candleQueries.add(rawQuery);
            String body = response(path, rawQuery);
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, bytes.length);
            try (var output = exchange.getResponseBody()) { output.write(bytes); }
        });
        server.start();
    }

    @AfterEach
    void stopProviderStub() {
        if (server != null) server.stop(0);
        if (executor != null) executor.shutdownNow();
    }

    @Test
    void tossQuoteMapsPriceCandlesAndDerivedValues() {
        var result = tossClient("test-client", "test-secret").quote("KRX:005930", "KRX", "005930");

        assertEquals("available", result.status());
        assertEquals("KRX:005930", result.companyId());
        assertEquals("toss", result.source().provider());
        assertEquals(700.0, result.quote().price());
        assertEquals("KRW", result.quote().currency());
        assertEquals(650.0, result.quote().previousClose());
        assertEquals(50.0, result.quote().change());
        assertEquals(50.0 / 650.0, result.quote().changeRate());
        assertEquals(710.0, result.quote().dayHigh());
        assertEquals(690.0, result.quote().dayLow());
        assertEquals(1234.0, result.quote().volume());
        assertEquals(750.0, result.quote().fiftyTwoWeekHigh());
        assertEquals(500.0, result.quote().fiftyTwoWeekLow());
        assertEquals(1000.0, result.quote().sharesOutstanding());
        assertEquals(700_000.0, result.quote().marketCap());
        assertEquals(1, tokenRequests.get());
    }

    @Test
    void fiftyTwoWeekRangeIgnoresCandlesOlderThanOneYear() {
        // The stub's oldest candle (2025-10-14, high 999 / low 1) is one day outside the year ending 2026-10-15.
        var quote = tossClient("test-client", "test-secret").quote("KRX:005930", "KRX", "005930").quote();

        assertEquals(750.0, quote.fiftyTwoWeekHigh());
        assertEquals(500.0, quote.fiftyTwoWeekLow());
    }

    @Test
    void tossWithoutCredentialsReturnsNotConnectedWithoutCallingProvider() {
        var result = tossClient("", "").quote("KRX:005930", "KRX", "005930");

        assertEquals("unavailable", result.status());
        assertEquals("not_connected", result.reasonCode());
        assertEquals(0, tokenRequests.get());
    }

    @Test
    void tossPriceWithoutProviderTimestampKeepsThePriceWithNullAsOf() {
        omitPriceTimestamp = true;
        var result = tossClient("test-client", "test-secret").quote("KRX:005930", "KRX", "005930");

        assertEquals("available", result.status());
        assertEquals(700.0, result.quote().price());
        assertNull(result.quote().asOf());
        // Without an observation time the session day is unknown, so session-derived values are not guessed.
        assertNull(result.quote().previousClose());
        assertNull(result.quote().dayHigh());
    }

    @Test
    void malformedPriceIsANonRetryableSourceFailureNotNoData() {
        lastPriceJson = "\"not-a-price\"";

        var error = assertThrows(MarketDataException.class,
                () -> tossClient("test-client", "test-secret").quote("KRX:005930", "KRX", "005930"));

        assertFalse(error.retryable());
    }

    @Test
    void sessionDayUsesTheMarketCalendarNotUtc() {
        // 2026-10-14T23:30Z is 2026-10-15 08:30 in Seoul: the 10-15 candle is today and 10-14 is the previous close.
        priceTimestamp = "2026-10-14T23:30:00Z";
        var quote = tossClient("test-client", "test-secret").quote("KRX:005930", "KRX", "005930").quote();

        assertEquals(650.0, quote.previousClose());
        assertEquals(710.0, quote.dayHigh());
        assertEquals(1234.0, quote.volume());
    }

    @Test
    void candlePaginationCursorWithOffsetIsPercentEncoded() {
        paginateCandles = true;
        tossClient("test-client", "test-secret").quote("KRX:005930", "KRX", "005930");

        assertEquals(2, candleQueries.size());
        assertTrue(candleQueries.get(1).contains("before=2026-10-15T00%3A00%3A00%2B09%3A00")
                || candleQueries.get(1).contains("before=2026-10-15T00:00:00%2B09:00"), candleQueries.get(1));
    }

    @Test
    void tossAuthenticationFailureIsNonRetryableSourceFailure() {
        tokenStatus = 401;

        var error = assertThrows(MarketDataException.class,
                () -> tossClient("test-client", "bad-secret").quote("KRX:005930", "KRX", "005930"));

        assertFalse(error.retryable());
        assertEquals(1, tokenRequests.get());
    }

    @Test
    void monthOfDailyBarsOldestFirstWithTheExchangeOffset() {
        exchangeDaily = true;
        var result = tossClient("test-client", "test-secret").prices("KRX:005930", "KRX", "005930", "1m", null, null);

        assertEquals("available", result.status());
        assertEquals("1m", result.period());
        assertEquals("1d", result.interval());
        assertEquals("KRW", result.currency());
        assertEquals("toss", result.source().provider());
        assertEquals(List.of("2026-10-14T00:00+09:00", "2026-10-15T00:00+09:00"),
                result.points().stream().map(p -> p.time()).toList());
        var last = result.points().get(1);
        assertEquals(695.0, last.open());
        assertEquals(700.0, last.close());
        assertEquals(1234.0, last.volume());
    }

    @Test
    void aDailyBarIsInTheRangeWhenItsExchangeDayOverlapsIt() {
        exchangeDaily = true;
        var result = tossClient("test-client", "test-secret").prices("KRX:005930", "KRX", "005930", "1m",
                kst("2026-10-15T00:00"), kst("2026-10-16T00:00"));
        assertEquals(List.of("2026-10-15T00:00+09:00"), result.points().stream().map(p -> p.time()).toList());

        var empty = tossClient("test-client", "test-secret").prices("KRX:005930", "KRX", "005930", "1m",
                kst("2026-01-01T00:00"), kst("2026-02-01T00:00"));
        assertEquals("unavailable", empty.status());
        assertEquals("no_data", empty.reasonCode());
    }

    @Test
    void anExactToCutsAUsDailyBarThatStartsAfterIt() {
        // NVDA's 10-15 bar starts at New York midnight, 13:00 KST: after a 10:00 KST cutoff, so it is not returned.
        exchangeDaily = true;
        var result = tossClient("test-client", "test-secret").prices("NASDAQ:NVDA", "NASDAQ", "NVDA", "1m",
                kst("2026-10-01T00:00"), kst("2026-10-15T10:00").plusNanos(1));
        assertEquals(List.of("2026-10-14T00:00-04:00"), result.points().stream().map(p -> p.time()).toList());
        assertEquals("USD", result.currency());
    }

    @Test
    void theLatestPointComesBackWhenTheChartSendsItsTimeAsTo() {
        exchangeDaily = true;
        var client = tossClient("test-client", "test-secret");
        var first = client.prices("KRX:005930", "KRX", "005930", "1m", null, null);
        var latest = first.points().getLast();

        java.time.Instant to = java.time.OffsetDateTime.parse(latest.time()).toInstant().plusNanos(1);
        var again = client.prices("KRX:005930", "KRX", "005930", "1m", TossMarketClient.periodStart("1m", to), to);
        assertEquals(latest, again.points().getLast());
    }

    @Test
    void dailyPagesStartAtTheRequestedEndSoAnOldRangeIsNotCutByThePageLimit() {
        exchangeDaily = true;
        tossClient("test-client", "test-secret").prices("KRX:005930", "KRX", "005930", "1m",
                kst("2026-01-01T00:00"), kst("2026-02-01T00:00"));
        assertTrue(candleQueries.get(0).contains("before=2026-01-31T15"), candleQueries.get(0));
    }

    @Test
    void aMalformedCandleIsAProviderFormatFailureNotASkippedRow() {
        exchangeDaily = true;
        malformedCandle = true;
        var error = assertThrows(MarketDataException.class,
                () -> tossClient("test-client", "test-secret").prices("KRX:005930", "KRX", "005930", "1m", null, null));
        assertFalse(error.retryable());
    }

    @Test
    void yearAggregatesDailyBarsIntoMondayWeeks() {
        var result = tossClient("test-client", "test-secret").prices("KRX:005930", "KRX", "005930", "1y", null, null);

        assertEquals("1wk", result.interval());
        // 10-14 and 10-15 fall in the week of Monday 10-12; the 2025 bars have no open and are left out.
        assertEquals(List.of(new CompanyPriceResponse.Point("2026-10-12T00:00+09:00", 645, 720, 640, 700, 2634.0)),
                result.points());
    }

    @Test
    void dayAggregatesMinuteBarsByTheirStartIntoFiveMinuteBuckets() {
        var client = tossClient("test-client", "test-secret");
        var result = client.prices("KRX:005930", "KRX", "005930", "1d", null, null);

        assertEquals("5m", result.interval());
        // Toss stamps a minute bar with its end: 12:01 and 12:02 start in the 12:00 bucket, 12:06 in 12:05.
        assertEquals(List.of(new CompanyPriceResponse.Point("2026-10-15T12:00+09:00", 100, 105, 99, 104, 15.0),
                new CompanyPriceResponse.Point("2026-10-15T12:05+09:00", 104, 104, 103, 103, 1.0)), result.points());
        // Today (10-16) is a holiday on the calendar stub, so the session is the previous business day: all of 10-15.
        assertEquals(new CompanyPriceResponse.Range("2026-10-15T09:00:00+09:00", "2026-10-15T15:30:00+09:00", "2026-10-15"),
                result.range());

        // The finished KST 10-15 is read once and then kept; the holiday is never read.
        client.prices("KRX:005930", "KRX", "005930", "1d", null, null);
        assertEquals(1, candleQueries.stream().filter(q -> q.contains("before=2026-10-15T15")).count());
        assertEquals(0, candleQueries.stream().filter(q -> q.contains("before=2026-10-16T15")).count());
    }

    @Test
    void aWeekEndingBeforeTheDstStartDoesNotTakeTheNextMondaysBar() {
        dstDaily = true;
        // Friday close before the 03-08 DST start: the week of 03-02 ends at 03-09 00:00 EDT, which is 167 hours on.
        var result = tossClient("test-client", "test-secret").prices("NASDAQ:NVDA", "NASDAQ", "NVDA", "1y", null,
                java.time.Instant.parse("2026-03-06T21:00:00Z").plusNanos(1));
        assertEquals(List.of(new CompanyPriceResponse.Point("2026-03-02T00:00-05:00", 110, 115, 109, 114, 5.0)),
                result.points());
    }

    @Test
    void dayIsTheCalendarSessionCutAtTo() {
        var client = tossClient("test-client", "test-secret");
        // During the session: from the open up to to; the bucket holding to stays whole.
        var open = client.prices("KRX:005930", "KRX", "005930", "1d", null,
                java.time.Instant.parse("2026-10-15T03:00:00Z").plusNanos(1));
        assertEquals(new CompanyPriceResponse.Range("2026-10-15T09:00:00+09:00", "2026-10-15T12:00:00+09:00", "2026-10-15"),
                open.range());
        assertEquals(List.of(new CompanyPriceResponse.Point("2026-10-15T12:00+09:00", 100, 105, 99, 104, 15.0)), open.points());

        // Sunday before the open: the calendar's previous business day (10-15; 10-16 is a holiday) as a whole session,
        // ending at its close, not at the requested to. Weekend and holiday days are never read.
        var weekend = client.prices("KRX:005930", "KRX", "005930", "1d", null, java.time.Instant.parse("2026-10-18T00:00:00Z"));
        assertEquals(new CompanyPriceResponse.Range("2026-10-15T09:00:00+09:00", "2026-10-15T15:30:00+09:00", "2026-10-15"),
                weekend.range());
        assertEquals(2, weekend.points().size());
        assertFalse(candleQueries.stream().anyMatch(q -> q.matches(".*before=2026-10-1[678]T15.*")));
    }

    @Test
    void anOpenSessionWithoutBarsIsNoDataNotThePreviousDay() {
        // A trading halt or no trades on a day the calendar says was open: no_data, never 10-15's prices.
        fridayOpen = true;
        var halted = tossClient("test-client", "test-secret").prices("KRX:005930", "KRX", "005930", "1d", null,
                java.time.Instant.parse("2026-10-16T03:00:00Z").plusNanos(1));
        assertEquals("unavailable", halted.status());
        assertEquals("no_data", halted.reasonCode());
        assertEquals(0, candleQueries.stream().filter(q -> q.contains("before=2026-10-15T15")).count());
    }

    @Test
    void aUsEarlyCloseEndsTheSessionAtTheCalendarClose() {
        // 2026-11-27 closes at 13:00 ET; a 14:00 ET request ends there and drops the 13:30 ET bar.
        var result = tossClient("test-client", "test-secret").prices("NASDAQ:NVDA", "NASDAQ", "NVDA", "1d", null,
                java.time.Instant.parse("2026-11-27T19:00:00Z").plusNanos(1));
        assertEquals(new CompanyPriceResponse.Range("2026-11-27T09:30:00-05:00", "2026-11-27T13:00:00-05:00", "2026-11-27"),
                result.range());
        assertEquals(List.of(new CompanyPriceResponse.Point("2026-11-27T12:00-05:00", 200, 202, 199, 201, 2.0)), result.points());
    }

    @Test
    void otherPeriodsReportTheirRangeWithoutASessionDate() {
        var result = tossClient("test-client", "test-secret").prices("KRX:005930", "KRX", "005930", "1w", null, null);
        assertEquals(new CompanyPriceResponse.Range("2026-10-09T12:00:00+09:00", "2026-10-16T12:00:00+09:00", null),
                result.range());
    }

    @Test
    void aRateLimitedPageIsRetriedAfterTheBucketRefills() {
        rateLimitOnce = true;
        var result = tossClient("test-client", "test-secret").prices("KRX:005930", "KRX", "005930", "1m", null, null);
        assertEquals("available", result.status());
        assertEquals(false, rateLimitOnce);
    }

    @Test
    void weekUsesHourBuckets() {
        var result = tossClient("test-client", "test-secret").prices("KRX:005930", "KRX", "005930", "1w", null, null);
        assertEquals("1h", result.interval());
        assertEquals(List.of(new CompanyPriceResponse.Point("2026-10-15T12:00+09:00", 100, 105, 99, 103, 16.0)),
                result.points());
        assertEquals("not_connected", tossClient("", "").prices("KRX:005930", "KRX", "005930", "1m", null, null).reasonCode());
    }

    private static java.time.Instant kst(String local) {
        return java.time.LocalDateTime.parse(local).atZone(java.time.ZoneId.of("Asia/Seoul")).toInstant();
    }

    @Test
    void barsWithoutACurrencyAreAProviderFormatFailureNotNoData() {
        omitStockCurrency = true;
        var error = assertThrows(MarketDataException.class,
                () -> tossClient("test-client", "test-secret").prices("KRX:005930", "KRX", "005930", "1m", null, null));
        assertFalse(error.retryable());
    }

    @Test
    void pricesProviderOutageIsARetryableSourceFailure() {
        providerStatus = 503;
        var error = assertThrows(MarketDataException.class,
                () -> tossClient("test-client", "test-secret").prices("KRX:005930", "KRX", "005930", "1m", null, null));
        assertTrue(error.retryable());
    }

    @Test
    void naverMapsDomesticMetricsAndKeepsProviderReferenceTime() {
        var result = naverClient().metrics("KRX:005930", "KRX", "005930");

        assertEquals("available", result.status());
        assertEquals("KRX:005930", result.companyId());
        assertEquals("naver", result.source().provider());
        assertFalse(result.source().official());
        assertEquals("2026-10-15T06:30:00Z", result.asOf().toString());
        assertEquals(List.of(
                new CompanyMetricsResponse.Metric("marketValue", "시가총액", "1,000조", "2026.06."),
                new CompanyMetricsResponse.Metric("per", "PER", "12.5배", null)), result.items());
    }

    @Test
    void naverTransientProviderFailureIsRetryable() {
        providerStatus = 503;

        var error = assertThrows(MarketDataException.class,
                () -> naverClient().metrics("KRX:005930", "KRX", "005930"));

        assertTrue(error.retryable());
    }

    @Test
    void naverUnsupportedSymbolReturnsUnavailableWithoutCallingProvider() {
        var result = naverClient().metrics("ORG:OPENAI", "ORG", "OPENAI");

        assertEquals("unavailable", result.status());
        assertEquals("unsupported_symbol", result.reasonCode());
        assertEquals(0, tokenRequests.get());
    }

    private TossMarketClient tossClient(String clientId, String clientSecret) {
        var settings = new CompanyMarketSettings("toss", clientId, clientSecret, baseUrl(), "naver",
                baseUrl(), baseUrl(), baseUrl(), Duration.ofSeconds(2));
        return new TossMarketClient(settings, JsonMapper.builder().build(), CLOCK);
    }

    private NaverMetricsClient naverClient() {
        var settings = new CompanyMarketSettings("toss", "", "", baseUrl(), "naver",
                baseUrl(), baseUrl(), baseUrl(), Duration.ofSeconds(2));
        return new NaverMetricsClient(settings, JsonMapper.builder().build());
    }

    private String baseUrl() { return "http://127.0.0.1:" + server.getAddress().getPort(); }

    /**
     * Toss market calendar stub (times in KST, as the provider documents). KR: 10-15 open; 10-16 a holiday unless
     * fridayOpen; 10-18 a Sunday. US: 11-27 closes early at 13:00 ET (03:00 KST on 11-28).
     */
    private String calendar(boolean kr, String rawQuery) {
        String date = rawQuery.replaceAll(".*date=([0-9-]{10}).*", "$1");
        if (!kr) return """
                {"result":{"today":{"date":"2026-11-27","regularMarket":{"startTime":"2026-11-27T23:30:00+09:00","endTime":"2026-11-28T03:00:00+09:00"}},
                  "previousBusinessDay":{"date":"2026-11-25","regularMarket":{"startTime":"2026-11-25T23:30:00+09:00","endTime":"2026-11-26T06:00:00+09:00"}},
                  "nextBusinessDay":{"date":"2026-11-30","regularMarket":{"startTime":"2026-11-30T23:30:00+09:00","endTime":"2026-12-01T06:00:00+09:00"}}}}
                """;
        boolean open = date.equals("2026-10-15") || (date.equals("2026-10-16") && fridayOpen);
        String previous = date.equals("2026-10-15") ? "2026-10-14" : fridayOpen && !date.equals("2026-10-16") ? "2026-10-16" : "2026-10-15";
        return "{\"result\":{\"today\":" + krDay(date, open) + ",\"previousBusinessDay\":" + krDay(previous, true)
                + ",\"nextBusinessDay\":" + krDay("2026-10-19", true) + "}}";
    }

    private static String krDay(String date, boolean open) {
        return "{\"date\":\"" + date + "\",\"integrated\":" + (open ? "{\"regularMarket\":{\"startTime\":\"" + date
                + "T09:00:00+09:00\",\"endTime\":\"" + date + "T15:30:00+09:00\"}}" : "null") + "}";
    }

    private String response(String path, String rawQuery) {
        if (path.equals("/oauth2/token")) return """
                {"access_token":"test-token","expires_in":3600}
                """;
        if (path.equals("/api/v1/prices")) return "{\"result\":[{\"symbol\":\"005930\",\"lastPrice\":" + lastPriceJson
                + ",\"currency\":\"KRW\"" + (omitPriceTimestamp ? "" : ",\"timestamp\":\"" + priceTimestamp + "\"") + "}]}";
        if (path.equals("/api/v1/candles") && paginateCandles && rawQuery != null && rawQuery.contains("before=")) return """
                {"result":{"candles":[],"nextBefore":null}}
                """;
        if (path.equals("/api/v1/candles") && paginateCandles) return """
                {"result":{"candles":[
                  {"timestamp":"2026-10-15T00:00:00+09:00","openPrice":695,"highPrice":710,"lowPrice":690,"closePrice":700,"volume":1234}
                ],"nextBefore":"2026-10-15T00:00:00+09:00"}}
                """;
        if (path.startsWith("/api/v1/market-calendar/")) return calendar(path.endsWith("/KR"), rawQuery);
        // NVDA on the 2026-11-27 early close (13:00 ET): one bar in the session, one at 13:30 ET after it.
        if (path.equals("/api/v1/candles") && rawQuery.contains("interval=1m") && rawQuery.contains("symbol=NVDA")) {
            return rawQuery.contains("before=2026-11-28T05") ? """
                {"result":{"candles":[
                  {"timestamp":"2026-11-27T18:31:00Z","openPrice":210,"highPrice":212,"lowPrice":209,"closePrice":211,"volume":3},
                  {"timestamp":"2026-11-27T17:01:00Z","openPrice":200,"highPrice":202,"lowPrice":199,"closePrice":201,"volume":2}
                ],"nextBefore":null}}
                """ : """
                {"result":{"candles":[],"nextBefore":null}}
                """;
        }
        if (path.equals("/api/v1/candles") && rawQuery.contains("interval=1m")) return rawQuery.contains("before=2026-10-15T15") ? """
                {"result":{"candles":[
                  {"timestamp":"2026-10-15T12:06:00+09:00","openPrice":104,"highPrice":104,"lowPrice":103,"closePrice":103,"volume":1},
                  {"timestamp":"2026-10-15T12:02:00+09:00","openPrice":100,"highPrice":105,"lowPrice":100,"closePrice":104,"volume":5},
                  {"timestamp":"2026-10-15T12:01:00+09:00","openPrice":100,"highPrice":101,"lowPrice":99,"closePrice":100,"volume":10}
                ],"nextBefore":null}}
                """ : """
                {"result":{"candles":[],"nextBefore":null}}
                """;
        if (path.equals("/api/v1/stocks")) return """
                {"result":[{"symbol":"005930","sharesOutstanding":1000,"currency":"KRW"},{"symbol":"NVDA","currency":"USD"}]}
                """.replace(omitStockCurrency ? ",\"currency\":\"KRW\"" : "never-in-body", "");
        if (path.equals("/api/v1/candles") && dstDaily) return """
                {"result":{"candles":[
                  {"timestamp":"2026-03-09T13:00:00+09:00","openPrice":120,"highPrice":125,"lowPrice":119,"closePrice":124,"volume":7},
                  {"timestamp":"2026-03-06T14:00:00+09:00","openPrice":110,"highPrice":115,"lowPrice":109,"closePrice":114,"volume":5}
                ],"nextBefore":null}}
                """;
        if (path.equals("/api/v1/candles") && exchangeDaily) {
            String day = rawQuery.contains("symbol=NVDA") ? "T13:00:00+09:00" : "T00:00:00+09:00";
            return """
                {"result":{"candles":[
                  {"timestamp":"2026-10-15DAY","openPrice":695,"highPrice":710,"lowPrice":690,"closePrice":700,"volume":1234},
                  {"timestamp":"2026-10-14DAY","openPrice":OPEN,"highPrice":720,"lowPrice":640,"closePrice":650,"volume":1400}
                ],"nextBefore":null}}
                """.replace("DAY", day).replace("OPEN", malformedCandle ? "\"n/a\"" : "645");
        }
        if (path.equals("/api/v1/candles")) return """
                {"result":{"candles":[
                  {"timestamp":"2026-10-15T00:00:00Z","openPrice":695,"highPrice":710,"lowPrice":690,"closePrice":700,"volume":1234},
                  {"timestamp":"2026-10-14T00:00:00Z","openPrice":645,"highPrice":720,"lowPrice":640,"closePrice":650,"volume":1400},
                  {"timestamp":"2025-10-15T00:00:00Z","highPrice":750,"lowPrice":500,"closePrice":550,"volume":1000},
                  {"timestamp":"2025-10-14T00:00:00Z","highPrice":999,"lowPrice":1,"closePrice":600,"volume":900}
                ]}}
                """;
        if (path.equals("/api/stock/005930/integration")) return """
                {"totalInfos":[
                  {"code":"marketValue","value":"1,000조","valueDesc":"2026.06."},
                  {"code":"per","value":" 12.5배 ","valueDesc":null},
                  {"code":"unrecognized","value":"ignored"}
                ]}
                """;
        if (path.equals("/api/stock/005930/basic")) return """
                {"localTradedAt":"2026-10-15T06:30:00Z"}
                """;
        return "{}";
    }
}
