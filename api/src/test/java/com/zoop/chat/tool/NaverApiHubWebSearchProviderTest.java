package com.zoop.chat.tool;

import static org.junit.jupiter.api.Assertions.*;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

/** Real-provider adapter contract without external network access. */
class NaverApiHubWebSearchProviderTest {
    private HttpServer server;
    private final AtomicReference<HttpExchange> seen = new AtomicReference<>();

    @BeforeEach
    void start() throws IOException {
        server = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0);
        server.createContext("/search/v1/webkr", exchange -> {
            seen.set(exchange);
            byte[] body = """
                    {"total":9,"start":1,"display":2,"items":[
                      {"title":"SK&amp;하이닉스 <b>HBM</b>","link":"https://news.example.com/a","description":"<b>HBM</b> 공급  확대"},
                      {"title":"두 번째","link":"https://news.example.com/b","description":"요약"}
                    ]}
                    """.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    @Test
    void sendsOnlyTheQueryAndSecretHeadersAndMapsABoundedPage() {
        var provider = provider();
        var page = provider.search("SK하이닉스 HBM", 2);

        assertEquals(2, page.hits().size());
        assertTrue(page.more());
        assertEquals("SK&하이닉스 HBM", page.hits().getFirst().title());
        assertEquals("HBM 공급 확대", page.hits().getFirst().snippet());
        assertNull(page.hits().getFirst().publishedAt());
        HttpExchange request = seen.get();
        assertNotNull(request);
        assertTrue(request.getRequestURI().getRawQuery().contains("query=SK%ED%95%98%EC%9D%B4%EB%8B%89%EC%8A%A4+HBM"));
        assertEquals("client-id", request.getRequestHeaders().getFirst("X-NCP-APIGW-API-KEY-ID"));
        assertEquals("client-secret", request.getRequestHeaders().getFirst("X-NCP-APIGW-API-KEY"));
    }

    @Test
    void providerErrorsAreUnavailableNotEmptyResults() {
        server.removeContext("/search/v1/webkr");
        server.createContext("/search/v1/webkr", exchange -> {
            exchange.sendResponseHeaders(429, -1);
            exchange.close();
        });
        assertThrows(ChatToolUnavailable.class, () -> provider().search("HBM", 1));
    }

    private NaverApiHubWebSearchProvider provider() {
        URI endpoint = URI.create("http://" + server.getAddress().getHostString() + ":" + server.getAddress().getPort()
                + "/search/v1/webkr");
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1))
                .followRedirects(HttpClient.Redirect.NEVER).build();
        return new NaverApiHubWebSearchProvider(client, endpoint, "client-id", "client-secret", new ObjectMapper());
    }
}
