package com.zoop.chat.mcp;

import com.zoop.common.json.Canonical;
import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * The access gate in front of {@code /mcp}, before any MCP message is read.
 *
 * <ul>
 * <li>A request with an {@code Origin} header is refused (403): the callers are servers (the model provider's MCP client),
 * never a browser page, so no browser can ride on a token.</li>
 * <li>A request needs {@code Authorization: Bearer <grant token>} that {@link ChatMcpGrants} verifies (401 otherwise, with
 * {@code WWW-Authenticate: Bearer}). The verified grant is passed on as a request attribute, never re-read from headers.</li>
 * <li>A token may make {@link #MAX_PER_MINUTE} requests per minute on this instance (429 with {@code Retry-After}). The
 * per-attempt call limit of the ledger bounds tool calls across instances; this bounds protocol traffic.</li>
 * </ul>
 * Tokens are never logged; the rate window keys on their digest.
 */
public final class ChatMcpAccessFilter implements Filter {
    static final String GRANT_ATTRIBUTE = ChatMcpAccessFilter.class.getName() + ".grant";
    static final int MAX_PER_MINUTE = 30;
    private static final Duration WINDOW = Duration.ofMinutes(1);
    private static final String BEARER = "Bearer ";

    private final ChatMcpGrants grants;
    private final Clock clock;
    /** Request times per token digest within the window, dropped once the grant expired. */
    private final Map<String, Window> windows = new ConcurrentHashMap<>();

    private record Window(Deque<Instant> times, Instant expiresAt) { }

    public ChatMcpAccessFilter(ChatMcpGrants grants, Clock clock) {
        this.grants = grants;
        this.clock = clock;
    }

    @Override
    public void doFilter(ServletRequest req, ServletResponse res, FilterChain chain) throws IOException, ServletException {
        var request = (HttpServletRequest) req;
        var response = (HttpServletResponse) res;
        if (request.getHeader("Origin") != null) {
            response.sendError(HttpServletResponse.SC_FORBIDDEN);
            return;
        }
        String authorization = request.getHeader("Authorization");
        Optional<ChatMcpGrant> grant = authorization != null && authorization.startsWith(BEARER)
                ? grants.verify(authorization.substring(BEARER.length()).trim()) : Optional.empty();
        if (grant.isEmpty()) {
            response.setHeader("WWW-Authenticate", "Bearer");
            response.sendError(HttpServletResponse.SC_UNAUTHORIZED);
            return;
        }
        if (!admit(Canonical.sha256(authorization), grant.get().expiresAt())) {
            response.setHeader("Retry-After", Long.toString(WINDOW.toSeconds()));
            response.sendError(429);
            return;
        }
        request.setAttribute(GRANT_ATTRIBUTE, grant.get());
        chain.doFilter(request, response);
    }

    private boolean admit(String key, Instant expiresAt) {
        Instant now = clock.instant();
        windows.values().removeIf(window -> !now.isBefore(window.expiresAt()));
        Window window = windows.computeIfAbsent(key, k -> new Window(new ArrayDeque<>(), expiresAt));
        synchronized (window) {
            while (!window.times().isEmpty() && !window.times().peekFirst().isAfter(now.minus(WINDOW))) {
                window.times().removeFirst();
            }
            if (window.times().size() >= MAX_PER_MINUTE) return false;
            window.times().addLast(now);
            return true;
        }
    }
}
