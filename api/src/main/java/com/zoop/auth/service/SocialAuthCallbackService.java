package com.zoop.auth.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;
import com.zoop.auth.config.SocialAuthSettings;
import com.zoop.auth.config.SocialAuthSettings.ProviderSettings;
import com.zoop.auth.repository.OAuthPendingRepository;
import com.zoop.auth.repository.OAuthPendingRow;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;

@Service
public class SocialAuthCallbackService {
    private final OAuthPendingRepository pending;
    private final SocialAuthSettings settings;
    private final SocialProviderGateway gateway;
    private final OidcIdTokenVerifier verifier;
    private final ObjectMapper mapper;
    private final Clock clock;
    private final SocialAuthCompletionService completion;

    public SocialAuthCallbackService(OAuthPendingRepository pending, SocialAuthSettings settings,
            SocialProviderGateway gateway, OidcIdTokenVerifier verifier, ObjectMapper mapper, Clock clock,
            SocialAuthCompletionService completion) {
        this.pending = pending;
        this.settings = settings;
        this.gateway = gateway;
        this.verifier = verifier;
        this.mapper = mapper;
        this.clock = clock;
        this.completion = completion;
    }

    public ResponseEntity<Void> callback(String providerId, String state, String code,
            String providerError, String cookieToken, String previousSessionCookie, String requestId) {
        ProviderSettings provider = settings.provider(providerId);
        boolean secureCookie = settings.pendingCookieSecure(provider);
        if (!settings.providerConfigured(provider) || !validToken(cookieToken)
                || !validToken(state) || (code != null && (code.isBlank() || code.length() > 4096))
                || (providerError != null && (providerError.isBlank() || providerError.length() > 128
                    || providerError.chars().anyMatch(Character::isISOControl)))
                || (code == null) == (providerError == null)) {
            return rejectWithoutClaim(cookieToken, secureCookie);
        }

        Instant now = clock.instant();
        String cookieHash = hash(cookieToken);
        String stateHash = hash(state);
        OAuthPendingRow row;
        try {
            row = pending.claimAuthorization(cookieHash, stateHash, providerId, now).orElse(null);
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
        if (row == null) return rejectWithoutClaim(cookieToken, secureCookie);

        JsonNode originalFlow = parseFlow(row.authFlow());
        if (!validClaimedFlow(originalFlow, provider, stateHash)) {
            consume(row, cookieHash);
            return redirect("/login", "failed", true, secureCookie);
        }
        String returnTo = originalFlow.path("returnTo").asString();
        if (providerError != null) {
            consume(row, cookieHash);
            return redirect(returnTo, "access_denied".equals(providerError) ? "cancelled" : "failed", true,
                    secureCookie);
        }

        try {
            String codeVerifier = originalFlow.path("codeVerifier").asString();
            SocialProviderGateway.TokenSet tokens = gateway.exchange(providerId, code,
                    provider.redirectUri(), codeVerifier);
            OidcIdTokenVerifier.VerifiedClaims claims = verifier.verify(providerId, provider,
                    tokens.idToken(), originalFlow.path("nonceHash").asString());

            String email = claims.email();
            boolean emailVerified = claims.emailVerified();
            if ("kakao".equals(providerId)) {
                JsonNode kakao = gateway.kakaoUserInfo(tokens.accessToken());
                JsonNode id = kakao.get("id");
                if (id == null || !id.isIntegralNumber() || id.asLong() <= 0
                        || !Long.toString(id.asLong()).equals(claims.subject())) {
                    throw new InvalidSocialAuthException();
                }
                JsonNode account = kakao.get("kakao_account");
                email = account == null ? null : text(account, "email");
                emailVerified = account != null && bool(account.get("is_email_valid"))
                        && bool(account.get("is_email_verified"));
            }
            if (!emailVerified || email == null || email.isBlank() || email.length() > 320
                    || email.chars().anyMatch(Character::isISOControl)) {
                email = null;
                emailVerified = false;
            }

            ObjectNode verifiedFlow = mapper.createObjectNode()
                    .put("schemaVersion", 1)
                    .put("phase", "identity_verified")
                    .put("provider", providerId)
                    .put("stateHash", stateHash)
                    .put("returnTo", returnTo)
                    .put("intent", text(originalFlow, "intent"))
                    .put("providerSubject", claims.subject())
                    .put("emailVerified", emailVerified);
            if ("link".equals(text(originalFlow, "intent"))) {
                verifiedFlow.put("memberId", text(originalFlow, "memberId"))
                        .put("sessionId", text(originalFlow, "sessionId"));
            }
            if (email == null) verifiedFlow.putNull("email"); else verifiedFlow.put("email", email);
            OAuthPendingRow verified = pending.completeVerification(row.id(), cookieHash,
                    mapper.writeValueAsString(verifiedFlow), clock.instant()).orElse(null);
            if (verified == null) return redirect(returnTo, "failed", true, secureCookie);
            return completion.complete(verified, cookieToken, previousSessionCookie, requestId);
        } catch (InvalidSocialAuthException exception) {
            consume(row, cookieHash);
            return redirect(returnTo, "failed", true, secureCookie);
        } catch (CustomException exception) {
            if (exception.getErrorCode() == ErrorCode.SOURCE_UNAVAILABLE) throw exception;
            consume(row, cookieHash);
            return redirect(returnTo, "failed", true, secureCookie);
        } catch (JacksonException exception) {
            consume(row, cookieHash);
            return redirect(returnTo, "failed", true, secureCookie);
        }
    }

    private boolean validClaimedFlow(JsonNode flow, ProviderSettings provider, String stateHash) {
        return flow != null && flow.isObject() && flow.path("schemaVersion").asInt() == 1
                && "callback_processing".equals(text(flow, "phase"))
                && provider.id().equals(text(flow, "provider"))
                && stateHash.equals(text(flow, "stateHash"))
                && provider.redirectUri().equals(text(flow, "redirectUri"))
                && ("login".equals(text(flow, "intent")) || "link".equals(text(flow, "intent")))
                && (!"link".equals(text(flow, "intent"))
                    || text(flow, "memberId") != null && text(flow, "sessionId") != null)
                && validToken(text(flow, "codeVerifier"))
                && SHA256.matcher(text(flow, "nonceHash") == null ? "" : text(flow, "nonceHash")).matches()
                && settings.allowedReturnPaths().contains(text(flow, "returnTo"));
    }

    private JsonNode parseFlow(String value) {
        try {
            JsonNode flow = mapper.readTree(value);
            return flow != null && flow.isObject() ? flow : null;
        } catch (JacksonException exception) {
            return null;
        }
    }

    private ResponseEntity<Void> rejectWithoutClaim(String cookieToken, boolean secureCookie) {
        if (validToken(cookieToken)) {
            try {
                pending.deleteByTokenHash(hash(cookieToken));
            } catch (DataAccessException exception) {
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
            }
        }
        return redirect("/login", "failed", true, secureCookie);
    }

    private void consume(OAuthPendingRow row, String cookieHash) {
        try {
            pending.consumeClaimedCallback(row.id(), cookieHash, clock.instant());
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    private ResponseEntity<Void> redirect(String returnTo, String result, boolean clearCookie, boolean secureCookie) {
        String location = settings.frontendLocation(returnTo, result);
        ResponseEntity.BodyBuilder response = ResponseEntity.status(302).header(HttpHeaders.LOCATION, location);
        if (clearCookie) response.header(HttpHeaders.SET_COOKIE, ResponseCookie.from(SocialAuthService.PENDING_COOKIE, "")
                .secure(secureCookie).httpOnly(true).sameSite("Lax").path("/api/v1/auth/social")
                .maxAge(Duration.ZERO).build().toString());
        return response.build();
    }

    private static String text(JsonNode node, String field) {
        JsonNode value = node == null ? null : node.get(field);
        return value == null || !value.isString() ? null : value.asString();
    }

    private static boolean bool(JsonNode value) {
        return value != null && value.isBoolean() && value.asBoolean();
    }

    private static boolean validToken(String token) {
        return token != null && token.matches("[A-Za-z0-9_-]{43}");
    }

    private static String hash(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.US_ASCII)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 unavailable", exception);
        }
    }

    private static final java.util.regex.Pattern SHA256 = java.util.regex.Pattern.compile("[0-9a-f]{64}");
}
