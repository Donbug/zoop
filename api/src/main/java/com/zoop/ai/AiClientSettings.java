package com.zoop.ai;

import java.net.URI;
import java.time.Duration;
import java.util.regex.Pattern;

/**
 * Validated, immutable settings of the production AI client. Construction fails closed with
 * {@link AiClientConfigurationException} (setting name only, never a value).
 *
 * <ul>
 *   <li>{@code baseUri}: {@code https} for any non-loopback host; plain {@code http} only for the literal hosts
 *       {@code localhost}, {@code 127.0.0.1} and {@code [::1]}. No user info, query or fragment. A path prefix of plain
 *       segments is allowed for a reverse proxy mount.</li>
 *   <li>{@code token}: the operator-issued bearer token of the app's principal, 32-512 characters of the service token alphabet.</li>
 *   <li>{@code connectTimeout} 100ms-30s, {@code requestTimeout} 100ms-120s (total deadline of one call),
 *       {@code maxResponseBytes} 64 KiB-32 MiB.</li>
 * </ul>
 */
public record AiClientSettings(URI baseUri, String token, Duration connectTimeout, Duration requestTimeout, int maxResponseBytes) {
    public static final int MAX_REQUEST_BYTES = 2_000_000;
    public static final Pattern TOKEN = Pattern.compile("[A-Za-z0-9._~+/-]{32,512}=*");
    private static final Pattern BASE_PATH = Pattern.compile("(/[A-Za-z0-9._~-]+)*/?");
    private static final Duration MIN_TIMEOUT = Duration.ofMillis(100);

    public AiClientSettings {
        if (baseUri == null) {
            throw new AiClientConfigurationException("base-url", "is required");
        }
        validateBase(baseUri);
        if (token == null || !TOKEN.matcher(token).matches()) {
            throw new AiClientConfigurationException("token", "is missing or not a service bearer token");
        }
        bound("connect-timeout", connectTimeout, Duration.ofSeconds(30));
        bound("request-timeout", requestTimeout, Duration.ofSeconds(120));
        if (maxResponseBytes < 64 * 1024 || maxResponseBytes > 32 * 1024 * 1024) {
            throw new AiClientConfigurationException("max-response-bytes", "must be between 65536 and 33554432");
        }
    }

    /** Parses a base URL string; the message never echoes the value. */
    public static AiClientSettings of(String baseUrl, String token, Duration connectTimeout, Duration requestTimeout,
                                      int maxResponseBytes) {
        if (baseUrl == null || baseUrl.isBlank()) {
            throw new AiClientConfigurationException("base-url", "is required");
        }
        URI uri;
        try {
            uri = new URI(baseUrl.strip());
        } catch (java.net.URISyntaxException error) {
            throw new AiClientConfigurationException("base-url", "is not a valid URL");
        }
        return new AiClientSettings(uri, token, connectTimeout, requestTimeout, maxResponseBytes);
    }

    private static void validateBase(URI uri) {
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(java.util.Locale.ROOT);
        String host = uri.getHost();
        if (!(scheme.equals("http") || scheme.equals("https")) || host == null) {
            throw new AiClientConfigurationException("base-url", "must be an absolute http(s) URL with a host");
        }
        if (uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null || uri.getPort() == 0
                || uri.getPort() > 65535 || uri.isOpaque()) {
            throw new AiClientConfigurationException("base-url", "must not contain user info, query, fragment or an invalid port");
        }
        String path = uri.getRawPath() == null ? "" : uri.getRawPath();
        if (!BASE_PATH.matcher(path).matches() || path.contains("/./") || path.contains("/../") || path.endsWith("/..")
                || path.endsWith("/.")) {
            throw new AiClientConfigurationException("base-url", "path must be plain segments");
        }
        if (scheme.equals("http") && !isLoopback(host)) {
            throw new AiClientConfigurationException("base-url", "must use https unless the host is loopback");
        }
    }

    private static boolean isLoopback(String host) {
        return host.equals("localhost") || host.equals("127.0.0.1") || host.equals("[::1]");
    }

    private static void bound(String setting, Duration value, Duration max) {
        if (value == null || value.compareTo(MIN_TIMEOUT) < 0 || value.compareTo(max) > 0) {
            throw new AiClientConfigurationException(setting, "must be between 100ms and " + max.toSeconds() + "s");
        }
    }

    /** The token is never printed. */
    @Override
    public String toString() {
        return "AiClientSettings[baseUri=" + baseUri.getScheme() + "://" + baseUri.getHost() + ", token=<redacted>]";
    }
}
