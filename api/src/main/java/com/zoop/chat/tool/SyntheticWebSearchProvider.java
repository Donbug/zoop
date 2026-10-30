package com.zoop.chat.tool;

import java.io.IOException;
import java.io.InputStream;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The only web search provider so far (web search design 7: none selected): hits written in a fixture on the classpath,
 * keyed by the exact checked query. Every page is under a reserved example domain, so nothing it returns can pass for a
 * real source. A query the fixture names as {@code unavailable} throws like a provider outage; any other unknown query
 * finds nothing. For local and test runs only; it never calls out.
 */
public final class SyntheticWebSearchProvider implements ChatWebSearchProvider {
    public static final String ID = "synthetic";
    static final String FIXTURE = "chat-web-fixtures/synthetic-v1.json";
    private static final String SCHEMA = "zoop-chat-web-fixture-1";
    private static final Set<String> EXAMPLE_HOSTS = Set.of("example.com", "example.org", "example.net");

    private final Map<String, List<Hit>> pages = new HashMap<>();
    private final Set<String> unavailable = new HashSet<>();

    public SyntheticWebSearchProvider() {
        this(FIXTURE);
    }

    SyntheticWebSearchProvider(String resource) {
        JsonNode fixture;
        try (InputStream in = getClass().getClassLoader().getResourceAsStream(resource)) {
            if (in == null) throw new IllegalStateException("no synthetic web fixture: " + resource);
            fixture = new ObjectMapper().readTree(in);
        } catch (IOException unreadable) {
            throw new IllegalStateException("the synthetic web fixture cannot be read", unreadable);
        }
        if (!SCHEMA.equals(fixture.path("schemaVersion").asString(""))) {
            throw new IllegalStateException("the synthetic web fixture is not " + SCHEMA);
        }
        for (var entry : fixture.path("queries").properties()) {
            List<Hit> hits = new ArrayList<>();
            for (JsonNode hit : entry.getValue()) {
                String url = hit.path("url").asString();
                String host = java.net.URI.create(url).getHost();
                if (host == null || EXAMPLE_HOSTS.stream().noneMatch(h -> host.equals(h) || host.endsWith("." + h))) {
                    throw new IllegalStateException("a synthetic hit must be under an example domain: " + url);
                }
                String published = hit.path("publishedAt").asString(null);
                hits.add(new Hit(url, hit.path("title").asString(), hit.path("snippet").asString(""),
                        published == null ? null : Instant.parse(published)));
            }
            pages.put(entry.getKey(), List.copyOf(hits));
        }
        fixture.path("unavailable").forEach(q -> unavailable.add(q.asString()));
    }

    @Override
    public String id() {
        return ID;
    }

    @Override
    public Page search(String query, int limit) {
        if (unavailable.contains(query)) throw new ChatToolUnavailable("the synthetic provider is down for " + query);
        List<Hit> hits = pages.getOrDefault(query, List.of());
        return new Page(hits.subList(0, Math.min(limit, hits.size())), hits.size() > limit);
    }
}
