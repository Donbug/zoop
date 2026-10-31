package com.zoop.chat.tool;

import java.net.URI;
import java.time.Instant;

/**
 * One web search hit as the server keeps it (web search design 3 and 6): only the title, URL, snippet and the provider's
 * publication time; a page body is never fetched. {@code id} is the server's own, made from the provider and URL, so the
 * same page found twice is one source. {@code publishedAt} is null when the provider gives none.
 */
public record ChatWebResult(String id, String url, String domain, String title, String snippet, Instant publishedAt,
        String provider, Instant searchedAt) {
    /** A snippet is passed on in at most this many code points. */
    public static final int MAX_SNIPPET = 500;
    public static final int MAX_TITLE = 300;

    public ChatWebResult {
        if (id == null || !id.startsWith("web-")) throw new IllegalArgumentException("a web result id is the server's");
        URI uri = URI.create(url);
        if (!("https".equals(uri.getScheme()) || "http".equals(uri.getScheme())) || uri.getHost() == null
                || uri.getUserInfo() != null) {
            throw new IllegalArgumentException("a web result is an http(s) page without credentials");
        }
        if (!uri.getHost().equalsIgnoreCase(domain)) throw new IllegalArgumentException("domain is the URL's host");
        if (title == null || title.isBlank() || title.codePointCount(0, title.length()) > MAX_TITLE) {
            throw new IllegalArgumentException("a web result needs a bounded title");
        }
        if (snippet == null || snippet.codePointCount(0, snippet.length()) > MAX_SNIPPET) {
            throw new IllegalArgumentException("a snippet is at most " + MAX_SNIPPET + " code points");
        }
        if (provider == null || provider.isBlank() || searchedAt == null) {
            throw new IllegalArgumentException("a web result names its provider and search time");
        }
    }
}
