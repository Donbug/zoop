package com.zoop.chat.tool;

import java.io.IOException;
import java.io.InputStream;
import java.net.Proxy;
import java.net.ProxySelector;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.springframework.web.util.HtmlUtils;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * NAVER API HUB web-document search. The provider receives only the already checked public query, follows no redirect,
 * uses no process proxy, reads a bounded JSON response and never fetches a result page. Credentials are request headers
 * supplied by the operator and are never included in errors or results.
 */
public final class NaverApiHubWebSearchProvider implements ChatWebSearchProvider {
    public static final String ID = "naver-api-hub-webkr";
    static final URI ENDPOINT = URI.create("https://naverapihub.apigw.ntruss.com/search/v1/webkr");
    static final int MAX_RESPONSE_BYTES = 1024 * 1024;
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(5);

    private final HttpClient client;
    private final URI endpoint;
    private final String clientId;
    private final String clientSecret;
    private final ObjectMapper json;

    public NaverApiHubWebSearchProvider(String clientId, String clientSecret) {
        this(noProxyClient(), ENDPOINT, clientId, clientSecret, new ObjectMapper());
    }

    NaverApiHubWebSearchProvider(HttpClient client, URI endpoint, String clientId, String clientSecret, ObjectMapper json) {
        this.client = java.util.Objects.requireNonNull(client);
        this.endpoint = java.util.Objects.requireNonNull(endpoint);
        this.clientId = credential(clientId, "client id");
        this.clientSecret = credential(clientSecret, "client secret");
        this.json = java.util.Objects.requireNonNull(json);
    }

    @Override
    public String id() {
        return ID;
    }

    @Override
    public Page search(String query, int limit) {
        if (limit < 1 || limit > ChatWebSearchTool.MAX_HITS) throw new IllegalArgumentException("invalid search limit");
        URI uri = URI.create(endpoint + "?query=" + URLEncoder.encode(query, StandardCharsets.UTF_8)
                + "&display=" + limit + "&start=1&format=json");
        HttpRequest request = HttpRequest.newBuilder(uri).timeout(REQUEST_TIMEOUT).GET()
                .header("Accept", "application/json")
                .header("User-Agent", "zoop-chat/1")
                .header("X-NCP-APIGW-API-KEY-ID", clientId)
                .header("X-NCP-APIGW-API-KEY", clientSecret)
                .build();
        try {
            HttpResponse<InputStream> response = client.send(request, HttpResponse.BodyHandlers.ofInputStream());
            try (InputStream body = response.body()) {
                if (response.statusCode() != 200) throw new ChatToolUnavailable("NAVER API HUB search failed");
                byte[] bytes = body.readNBytes(MAX_RESPONSE_BYTES + 1);
                if (bytes.length > MAX_RESPONSE_BYTES) throw new ChatToolUnavailable("NAVER API HUB response is too large");
                return parse(bytes, limit);
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new ChatToolUnavailable("NAVER API HUB search was interrupted", interrupted);
        } catch (IOException | RuntimeException failure) {
            if (failure instanceof ChatToolUnavailable unavailable) throw unavailable;
            throw new ChatToolUnavailable("NAVER API HUB search is unavailable", failure);
        }
    }

    private Page parse(byte[] bytes, int limit) throws IOException {
        JsonNode root = json.readTree(bytes);
        JsonNode items = root.path("items");
        if (!items.isArray()) throw new IOException("items is not an array");
        List<Hit> hits = new ArrayList<>();
        for (JsonNode item : items) {
            if (hits.size() == limit) break;
            String link = item.path("link").asString("").strip();
            String title = clean(item.path("title").asString(""));
            String description = clean(item.path("description").asString(""));
            if (!link.isEmpty() && !title.isEmpty()) hits.add(new Hit(link, title, description, null));
        }
        int display = root.path("display").asInt(items.size());
        int start = root.path("start").asInt(1);
        long total = root.path("total").asLong(hits.size());
        return new Page(hits, total > (long) start - 1 + Math.max(display, hits.size()));
    }

    static String clean(String value) {
        String withoutHighlights = value.replaceAll("(?i)</?b>", "");
        return HtmlUtils.htmlUnescape(withoutHighlights).strip().replaceAll("\\s+", " ");
    }

    private static String credential(String value, String name) {
        if (value == null || value.length() < 5 || value.length() > 512
                || value.chars().anyMatch(c -> c < 0x21 || c > 0x7e)) {
            throw new IllegalStateException("NAVER API HUB " + name + " is missing or invalid");
        }
        return value;
    }

    private static HttpClient noProxyClient() {
        return HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).followRedirects(HttpClient.Redirect.NEVER)
                .proxy(new ProxySelector() {
                    @Override public List<Proxy> select(URI uri) { return List.of(Proxy.NO_PROXY); }
                    @Override public void connectFailed(URI uri, java.net.SocketAddress address, IOException failure) { }
                }).build();
    }
}
