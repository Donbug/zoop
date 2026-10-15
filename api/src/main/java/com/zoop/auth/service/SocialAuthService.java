package com.zoop.auth.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.List;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;
import com.zoop.auth.config.SocialAuthSettings;
import com.zoop.auth.config.SocialAuthSettings.ProviderSettings;
import com.zoop.auth.dto.SocialProviderOut;
import com.zoop.auth.dto.SocialAuthorizationResponse;
import com.zoop.auth.dto.SocialProvidersResponse;
import com.zoop.auth.repository.OAuthPendingRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.util.UriComponentsBuilder;

@Service
public class SocialAuthService {
    public static final String PENDING_COOKIE = "zoop_oauth_pending";
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final List<SocialProviderOut> PROVIDERS = List.of(
            new SocialProviderOut("google", "Google"), new SocialProviderOut("kakao", "카카오"));
    private final OAuthPendingRepository pending;
    private final SocialAuthSettings settings;
    private final AuthRateLimiter rates;
    private final ObjectMapper mapper;
    private final Clock clock;
    private final MemberSessionService sessions;

    public SocialAuthService(OAuthPendingRepository pending, SocialAuthSettings settings,
            AuthRateLimiter rates, ObjectMapper mapper, Clock clock, MemberSessionService sessions) {
        this.pending = pending;
        this.settings = settings;
        this.rates = rates;
        this.mapper = mapper;
        this.clock = clock;
        this.sessions = sessions;
    }

    public SocialProvidersResponse listProviders(String cursor, Integer requestedLimit) {
        int limit = requestedLimit == null ? 20 : requestedLimit;
        if (limit < 1 || limit > 100) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        int after = 0;
        if (cursor != null) {
            Cursor decoded = decodeCursor(cursor);
            if (requestedLimit != null && requestedLimit != decoded.limit()) {
                throw new CustomException(ErrorCode.INVALID_CURSOR);
            }
            after = decoded.after();
            limit = decoded.limit();
        }
        int end = Math.min(PROVIDERS.size(), after + limit);
        List<SocialProviderOut> items = PROVIDERS.subList(after, end);
        String next = end < PROVIDERS.size() ? encodeCursor(end, limit) : null;
        return new SocialProvidersResponse(items, next);
    }

    @Transactional
    public ResponseEntity<Void> authorize(String providerId, String returnTo, String clientIp,
            String previousPendingCookie) {
        AuthorizationStart start = start(providerId, returnTo, clientIp, previousPendingCookie,
                "login", null, null);
        return ResponseEntity.status(302)
                .header(HttpHeaders.LOCATION, start.authorizationUrl())
                .header(HttpHeaders.SET_COOKIE, start.cookie().toString())
                .build();
    }

    @Transactional
    public ResponseEntity<SocialAuthorizationResponse> authorizeLink(String providerId, String returnTo,
            String clientIp, String previousPendingCookie, String memberSessionCookie, String csrfToken) {
        sessions.verifyCsrf(memberSessionCookie, csrfToken);
        MemberSessionService.SessionBinding binding = sessions.currentBinding(memberSessionCookie);
        AuthorizationStart start = start(providerId, returnTo, clientIp, previousPendingCookie,
                "link", binding.memberId(), binding.sessionId());
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, start.cookie().toString())
                .body(new SocialAuthorizationResponse(start.authorizationUrl()));
    }

    private AuthorizationStart start(String providerId, String returnTo, String clientIp,
            String previousPendingCookie, String intent, String memberId, String sessionId) {
        ProviderSettings provider = settings.provider(providerId);
        if (provider == null) {
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        }
        if (!settings.providerConfigured(provider)) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        String safeReturnTo = validateReturnTo(returnTo);
        rates.recordSocialStartIpAttempt(clientIp, settings.ipStartLimit());

        String oldBrowserKey = validToken(previousPendingCookie) ? hashToken(previousPendingCookie) : null;
        if (oldBrowserKey != null) {
            rates.recordSocialStartBrowserAttempt(oldBrowserKey, settings.browserStartLimit());
            pending.deleteByTokenHash(oldBrowserKey);
        }

        Instant now = clock.instant();
        Instant expiresAt = now.plus(settings.pendingTtl());
        // Retaining the browser token keeps the per-browser rolling limit stable across starts.
        String cookieToken = validToken(previousPendingCookie) ? previousPendingCookie : randomToken();
        String state = randomToken();
        String nonce = randomToken();
        String verifier = randomToken();
        String tokenHash = hashToken(cookieToken);
        String stateHash = hashToken(state);
        String nonceHash = hashToken(nonce);
        String challenge = base64Url(sha256(verifier.getBytes(StandardCharsets.US_ASCII)));
        String flowId = randomToken();

        ObjectNode flow = mapper.createObjectNode()
                .put("schemaVersion", 1)
                .put("phase", "authorization_pending")
                .put("provider", provider.id())
                .put("stateHash", stateHash)
                .put("nonceHash", nonceHash)
                .put("codeVerifier", verifier)
                .put("redirectUri", provider.redirectUri())
                .put("returnTo", safeReturnTo)
                .put("intent", intent);
        if ("link".equals(intent)) flow.put("memberId", memberId).put("sessionId", sessionId);
        try {
            pending.insert(flowId, tokenHash, mapper.writeValueAsString(flow), now, expiresAt);
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }

        String authorizationUrl = UriComponentsBuilder.fromUriString(provider.authorizationEndpoint())
                .queryParam("client_id", provider.clientId())
                .queryParam("redirect_uri", provider.redirectUri())
                .queryParam("response_type", "code")
                .queryParam("scope", provider.scope())
                .queryParam("state", state)
                .queryParam("nonce", nonce)
                .queryParam("code_challenge", challenge)
                .queryParam("code_challenge_method", "S256")
                .build().encode().toUriString();
        ResponseCookie cookie = ResponseCookie.from(PENDING_COOKIE, cookieToken)
                .httpOnly(true).secure(settings.pendingCookieSecure(provider)).sameSite("Lax")
                .path("/api/v1/auth/social").maxAge(settings.pendingTtl()).build();
        return new AuthorizationStart(authorizationUrl, cookie);
    }

    private String validateReturnTo(String value) {
        String path = value == null || value.isBlank() ? "/login" : value;
        if (path.length() > 512 || !settings.allowedReturnPaths().contains(path)
                || !path.startsWith("/") || path.startsWith("//") || path.indexOf('\\') >= 0
                || path.chars().anyMatch(Character::isISOControl)
                || path.contains("%2f") || path.contains("%2F") || path.contains("%5c")
                || path.contains("%5C")) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        return path;
    }

    private static boolean validToken(String value) {
        return value != null && value.matches("[A-Za-z0-9_-]{43}");
    }

    private static String randomToken() {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        return base64Url(bytes);
    }

    private static String hashToken(String value) {
        return HexFormat.of().formatHex(sha256(value.getBytes(StandardCharsets.US_ASCII)));
    }

    private static byte[] sha256(byte[] value) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(value);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 unavailable", exception);
        }
    }

    private static String base64Url(byte[] value) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(value);
    }

    private static String encodeCursor(int after, int limit) {
        return base64Url(("v1:" + after + ":" + limit).getBytes(StandardCharsets.US_ASCII));
    }

    private static Cursor decodeCursor(String value) {
        try {
            if (value.length() > 128) throw new IllegalArgumentException();
            String decoded = new String(Base64.getUrlDecoder().decode(value), StandardCharsets.US_ASCII);
            String[] parts = decoded.split(":", -1);
            int after = Integer.parseInt(parts[1]);
            int limit = Integer.parseInt(parts[2]);
            if (parts.length != 3 || !"v1".equals(parts[0]) || after < 1
                    || after >= PROVIDERS.size() || limit < 1 || limit > 100) {
                throw new IllegalArgumentException();
            }
            return new Cursor(after, limit);
        } catch (RuntimeException exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR);
        }
    }

    private record Cursor(int after, int limit) { }

    private record AuthorizationStart(String authorizationUrl, ResponseCookie cookie) { }
}
