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
import com.zoop.company.market.dto.CompanyMetricsResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.*;

class CompanyMarketClientsTest {
    private HttpServer server;
    private java.util.concurrent.ExecutorService executor;
    private final AtomicInteger tokenRequests = new AtomicInteger();
    private volatile int tokenStatus = 200;
    private volatile int providerStatus = 200;
    private volatile boolean omitPriceTimestamp;

    @BeforeEach
    void startProviderStub() throws IOException {
        server = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0);
        executor = Executors.newCachedThreadPool();
        server.setExecutor(executor);
        server.createContext("/", exchange -> {
            String path = exchange.getRequestURI().getPath();
            int status = path.equals("/oauth2/token") ? tokenStatus : providerStatus;
            String body = response(path);
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, bytes.length);
            try (var output = exchange.getResponseBody()) { output.write(bytes); }
            if (path.equals("/oauth2/token")) tokenRequests.incrementAndGet();
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
    void tossWithoutCredentialsReturnsNotConnectedWithoutCallingProvider() {
        var result = tossClient("", "").quote("KRX:005930", "KRX", "005930");

        assertEquals("unavailable", result.status());
        assertEquals("not_connected", result.reasonCode());
        assertEquals(0, tokenRequests.get());
    }

    @Test
    void tossPriceWithoutProviderTimestampIsUnavailableRatherThanAnIncompleteQuote() {
        omitPriceTimestamp = true;
        var result = tossClient("test-client", "test-secret").quote("KRX:005930", "KRX", "005930");

        assertEquals("unavailable", result.status());
        assertEquals("no_data", result.reasonCode());
        assertNull(result.quote());
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
        return new TossMarketClient(settings, JsonMapper.builder().build());
    }

    private NaverMetricsClient naverClient() {
        var settings = new CompanyMarketSettings("toss", "", "", baseUrl(), "naver",
                baseUrl(), baseUrl(), baseUrl(), Duration.ofSeconds(2));
        return new NaverMetricsClient(settings, JsonMapper.builder().build());
    }

    private String baseUrl() { return "http://127.0.0.1:" + server.getAddress().getPort(); }

    private String response(String path) {
        if (path.equals("/oauth2/token")) return """
                {"access_token":"test-token","expires_in":3600}
                """;
        if (path.equals("/api/v1/prices")) return (omitPriceTimestamp ? """
                {"result":[{"symbol":"005930","lastPrice":700,"currency":"KRW"}]}
                """ : """
                {"result":[{"symbol":"005930","lastPrice":700,"currency":"KRW","timestamp":"2026-10-15T06:30:00Z"}]}
                """);
        if (path.equals("/api/v1/stocks")) return """
                {"result":[{"symbol":"005930","sharesOutstanding":1000}]}
                """;
        if (path.equals("/api/v1/candles")) return """
                {"result":{"candles":[
                  {"timestamp":"2026-10-15T00:00:00Z","highPrice":710,"lowPrice":690,"closePrice":700,"volume":1234},
                  {"timestamp":"2026-10-14T00:00:00Z","highPrice":720,"lowPrice":640,"closePrice":650,"volume":1400},
                  {"timestamp":"2025-10-15T00:00:00Z","highPrice":750,"lowPrice":500,"closePrice":550,"volume":1000}
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
