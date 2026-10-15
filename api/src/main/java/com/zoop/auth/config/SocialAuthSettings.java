package com.zoop.auth.config;

import java.net.URI;
import java.time.Duration;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

@Component
public class SocialAuthSettings {
    private final Duration pendingTtl;
    private final int ipStartLimit;
    private final int browserStartLimit;
    private final Set<String> allowedReturnPaths;
    private final boolean allowInsecureLocalhost;
    private final ProviderSettings google;
    private final ProviderSettings kakao;

    @Autowired
    public SocialAuthSettings(
            @Value("${ZOOP_AUTH_SOCIAL_PENDING_TTL:PT10M}") Duration pendingTtl,
            @Value("${ZOOP_AUTH_SOCIAL_START_IP_LIMIT:30}") int ipStartLimit,
            @Value("${ZOOP_AUTH_SOCIAL_START_BROWSER_LIMIT:10}") int browserStartLimit,
            @Value("${ZOOP_AUTH_SOCIAL_RETURN_PATHS:/login,/signup,/}") String returnPaths,
            @Value("${ZOOP_AUTH_SOCIAL_ALLOW_INSECURE_LOCALHOST:false}") boolean allowInsecureLocalhost,
            @Value("${ZOOP_AUTH_SOCIAL_GOOGLE_CLIENT_ID:}") String googleClientId,
            @Value("${ZOOP_AUTH_SOCIAL_GOOGLE_CLIENT_SECRET:}") String googleClientSecret,
            @Value("${ZOOP_AUTH_SOCIAL_GOOGLE_REDIRECT_URI:}") String googleRedirectUri,
            @Value("${ZOOP_AUTH_SOCIAL_KAKAO_CLIENT_ID:}") String kakaoClientId,
            @Value("${ZOOP_AUTH_SOCIAL_KAKAO_CLIENT_SECRET:}") String kakaoClientSecret,
            @Value("${ZOOP_AUTH_SOCIAL_KAKAO_REDIRECT_URI:}") String kakaoRedirectUri) {
        if (pendingTtl == null || pendingTtl.isNegative() || pendingTtl.isZero()
                || pendingTtl.compareTo(Duration.ofMinutes(30)) > 0
                || ipStartLimit < 1 || browserStartLimit < 1) {
            throw new IllegalArgumentException("Invalid social auth limits or pending TTL");
        }
        this.pendingTtl = pendingTtl;
        this.ipStartLimit = ipStartLimit;
        this.browserStartLimit = browserStartLimit;
        this.allowInsecureLocalhost = allowInsecureLocalhost;
        this.allowedReturnPaths = Arrays.stream(returnPaths.split(",", -1)).map(String::trim)
                .filter(value -> !value.isEmpty()).collect(Collectors.toUnmodifiableSet());
        this.google = new ProviderSettings("google", "Google", "https://accounts.google.com/o/oauth2/v2/auth",
                googleClientId, googleClientSecret, googleRedirectUri, "openid email");
        this.kakao = new ProviderSettings("kakao", "카카오", "https://kauth.kakao.com/oauth/authorize",
                kakaoClientId, kakaoClientSecret, kakaoRedirectUri, "openid account_email");
        if (this.allowedReturnPaths.isEmpty() || this.allowedReturnPaths.stream().anyMatch(path ->
                !path.startsWith("/") || path.startsWith("//") || path.indexOf('\\') >= 0
                        || path.indexOf('?') >= 0 || path.indexOf('#') >= 0)) {
            throw new IllegalArgumentException("Social return paths must be relative path allowlist entries");
        }
    }

    public Duration pendingTtl() { return pendingTtl; }
    public int ipStartLimit() { return ipStartLimit; }
    public int browserStartLimit() { return browserStartLimit; }
    public Set<String> allowedReturnPaths() { return allowedReturnPaths; }
    public boolean allowInsecureLocalhost() { return allowInsecureLocalhost; }
    public boolean providerConfigured(ProviderSettings provider) {
        return provider != null && provider.configured(allowInsecureLocalhost);
    }
    public boolean pendingCookieSecure(ProviderSettings provider) {
        return provider == null || !provider.redirectUri().startsWith("http://");
    }

    public ProviderSettings provider(String id) {
        return switch (id) {
            case "google" -> google;
            case "kakao" -> kakao;
            default -> null;
        };
    }

    public record ProviderSettings(String id, String name, String authorizationEndpoint,
            String clientId, String clientSecret, String redirectUri, String scope) {
        public boolean configured(boolean allowInsecureLocalhost) {
            if (clientId == null || clientId.isBlank() || clientSecret == null || clientSecret.isBlank()
                    || redirectUri == null || redirectUri.isBlank()) {
                return false;
            }
            try {
                URI uri = URI.create(redirectUri);
                if (uri.getHost() == null || uri.getUserInfo() != null || uri.getFragment() != null
                        || uri.getQuery() != null) return false;
                if ("https".equalsIgnoreCase(uri.getScheme())) return true;
                if (!allowInsecureLocalhost || !"http".equalsIgnoreCase(uri.getScheme())) return false;
                String host = uri.getHost().toLowerCase(java.util.Locale.ROOT);
                return host.equals("localhost") || host.equals("127.0.0.1")
                        || host.equals("::1") || host.equals("[::1]");
            } catch (IllegalArgumentException exception) {
                return false;
            }
        }
    }
}
