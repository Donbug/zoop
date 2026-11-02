package com.zoop.chat.tool;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.function.Supplier;

/**
 * Instance-local provider request cache for {@link ChatWebSearchTool}. Successful pages, including a successful empty page,
 * are reused for a short bounded lifetime. Provider failures are never cached. Calls for one key that overlap join one
 * flight; the caller's normal tool deadline still bounds its wait.
 *
 * <p>The key is the complete current provider request: provider, normalized query and result limit. A later provider
 * contract that adds language, period or filters must add them to {@link Key}; a value absent from the request must not be
 * guessed here. This cache does not change chat call accounting: approval and reservation happen before the tool reaches
 * it, so a cache hit still consumes one job/member/project search attempt.
 */
final class ChatWebSearchRequestCache {
    static final Duration DEFAULT_TTL = Duration.ofMinutes(5);
    static final int DEFAULT_MAX_ENTRIES = 256;
    static final Duration MAX_TTL = Duration.ofHours(1);
    static final int MAX_ENTRIES = 10_000;

    record Search(ChatWebSearchProvider.Page page, Instant searchedAt) { }

    private record Key(String provider, String query, int limit) { }

    private record Entry(Search search, Instant expiresAt) { }

    private final Clock clock;
    private final Duration ttl;
    private final int maxEntries;
    /** Access-order LRU; all access is under this object's monitor. */
    private final Map<Key, Entry> entries = new LinkedHashMap<>(16, 0.75f, true);
    private final ConcurrentHashMap<Key, CompletableFuture<Search>> flights = new ConcurrentHashMap<>();

    ChatWebSearchRequestCache(Clock clock, Duration ttl, int maxEntries) {
        if (ttl == null || ttl.isZero() || ttl.isNegative() || ttl.compareTo(MAX_TTL) > 0) {
            throw new IllegalArgumentException("web search cache ttl must be over zero and at most " + MAX_TTL);
        }
        if (maxEntries < 1 || maxEntries > MAX_ENTRIES) {
            throw new IllegalArgumentException("web search cache entries must be 1 to " + MAX_ENTRIES);
        }
        this.clock = clock;
        this.ttl = ttl;
        this.maxEntries = maxEntries;
    }

    Search search(String provider, String query, int limit, Supplier<ChatWebSearchProvider.Page> lookup) {
        Key key = new Key(provider, query, limit);
        Search hit = cached(key);
        if (hit != null) return hit;

        CompletableFuture<Search> mine = new CompletableFuture<>();
        CompletableFuture<Search> earlier = flights.putIfAbsent(key, mine);
        if (earlier != null) return joined(earlier);
        try {
            // A flight may have stored and removed itself between this caller's first lookup and putIfAbsent.
            hit = cached(key);
            if (hit != null) {
                mine.complete(hit);
                return hit;
            }
            ChatWebSearchProvider.Page page = Objects.requireNonNull(lookup.get(), "a web provider returns a page");
            Search loaded = new Search(page, clock.instant());
            keep(key, loaded);
            mine.complete(loaded);
            return loaded;
        } catch (RuntimeException | Error failure) {
            mine.completeExceptionally(failure);
            throw failure;
        } finally {
            flights.remove(key, mine);
        }
    }

    private synchronized Search cached(Key key) {
        Entry entry = entries.get(key);
        if (entry == null) return null;
        if (!clock.instant().isBefore(entry.expiresAt())) {
            entries.remove(key);
            return null;
        }
        return entry.search();
    }

    private synchronized void keep(Key key, Search search) {
        entries.put(key, new Entry(search, search.searchedAt().plus(ttl)));
        while (entries.size() > maxEntries) entries.remove(entries.keySet().iterator().next());
    }

    private static Search joined(CompletableFuture<Search> earlier) {
        try {
            return earlier.get();
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new ChatToolUnavailable("web search cache wait interrupted", interrupted);
        } catch (ExecutionException failed) {
            if (failed.getCause() instanceof RuntimeException runtime) throw runtime;
            if (failed.getCause() instanceof Error error) throw error;
            throw new ChatToolUnavailable("web search cache flight failed", failed.getCause());
        }
    }
}
