package com.zoop.auth.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;
import com.zoop.auth.config.SocialAuthSettings;
import com.zoop.auth.repository.MemberAuthRepository;
import com.zoop.auth.repository.OAuthPendingRepository;
import com.zoop.auth.repository.OAuthPendingRow;
import com.zoop.auth.repository.SocialIdentityRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Resolves a verified provider identity to a login, signup consent, or safe account-link prompt. */
@Service
public class SocialAuthCompletionService {
    private static final SecureRandom RANDOM = new SecureRandom();
    private final OAuthPendingRepository pending;
    private final SocialIdentityRepository identities;
    private final MemberAuthRepository members;
    private final MemberSessionService sessions;
    private final SocialAuthSettings settings;
    private final ObjectMapper mapper;
    private final Clock clock;

    public SocialAuthCompletionService(OAuthPendingRepository pending, SocialIdentityRepository identities,
            MemberAuthRepository members, MemberSessionService sessions, SocialAuthSettings settings,
            ObjectMapper mapper, Clock clock) {
        this.pending = pending;
        this.identities = identities;
        this.members = members;
        this.sessions = sessions;
        this.settings = settings;
        this.mapper = mapper;
        this.clock = clock;
    }

    @Transactional
    public ResponseEntity<Void> complete(OAuthPendingRow verified, String browserCookie,
            String previousSessionCookie, String requestId) {
        String cookieHash = hash(browserCookie);
        JsonNode flow = parse(verified.authFlow());
        String provider = text(flow, "provider");
        String returnTo = text(flow, "returnTo");
        var providerSettings = provider == null ? null : settings.provider(provider);
        boolean secure = settings.pendingCookieSecure(providerSettings);
        if (!validFlow(flow) || !verified.tokenHash().equals(cookieHash)
                || providerSettings == null || !settings.allowedReturnPaths().contains(returnTo)) {
            consume(verified, cookieHash);
            return redirect("/login", "failed", null, secure);
        }

        try {
            if ("link".equals(text(flow, "intent"))) {
                return completeLink(verified, cookieHash, flow, previousSessionCookie, returnTo, secure);
            }
            var linked = identities.findByProviderSubject(provider, text(flow, "providerSubject"));
            if (linked.isPresent()) {
                var member = members.findById(linked.get().memberId());
                if (member.isEmpty() || !"active".equals(member.get().status())) {
                    consume(verified, cookieHash);
                    return redirect(returnTo, "failed", null, secure);
                }
                if (pending.consumeIdentityVerified(verified.id(), cookieHash, clock.instant()).isEmpty()) {
                    return redirect(returnTo, "failed", clearPending(secure), secure);
                }
                var issued = sessions.issue(member.get().id(), previousSessionCookie, requestId);
                return redirect(returnTo, null, issued.cookie().toString(), secure, clearPending(secure));
            }

            EmailAddress email = usableEmail(flow);
            if (email == null) {
                consume(verified, cookieHash);
                return redirect("/login", "email_required", null, secure);
            }
            if (members.findByEmailKey(email.key()).isPresent()) {
                consume(verified, cookieHash);
                return redirect("/login", "link_required", null, secure);
            }

            String nextCookie = randomToken();
            Instant now = clock.instant();
            ObjectNode consent = mapper.createObjectNode()
                    .put("schemaVersion", 1)
                    .put("phase", "consent_pending")
                    .put("provider", provider)
                    .put("stateHash", text(flow, "stateHash"))
                    .put("providerSubject", text(flow, "providerSubject"))
                    .put("email", email.value())
                    .put("emailVerified", true);
            var rotated = pending.rotateToConsent(verified.id(), cookieHash, hash(nextCookie),
                    mapper.writeValueAsString(consent), now, now.plus(settings.pendingTtl()));
            if (rotated.isEmpty()) return redirect("/login", "failed", clearPending(secure), secure);
            ResponseCookie cookie = ResponseCookie.from(SocialAuthService.PENDING_COOKIE, nextCookie)
                    .httpOnly(true).secure(secure).sameSite("Lax").path("/api/v1/auth/social")
                    .maxAge(settings.pendingTtl()).build();
            return redirect("/signup", "pending", cookie.toString(), secure);
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        } catch (JacksonException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    private boolean validFlow(JsonNode flow) {
        String intent = text(flow, "intent");
        return flow != null && flow.isObject() && flow.path("schemaVersion").asInt() == 1
                && "identity_verified".equals(text(flow, "phase"))
                && ("google".equals(text(flow, "provider")) || "kakao".equals(text(flow, "provider")))
                && ("login".equals(intent) || "link".equals(intent))
                && text(flow, "providerSubject") != null && !text(flow, "providerSubject").isBlank()
                && text(flow, "providerSubject").length() <= 512
                && text(flow, "stateHash") != null && text(flow, "stateHash").matches("[0-9a-f]{64}")
                && flow.path("emailVerified").isBoolean()
                && (!"link".equals(intent) || text(flow, "memberId") != null
                    && text(flow, "sessionId") != null);
    }

    private ResponseEntity<Void> completeLink(OAuthPendingRow verified, String cookieHash, JsonNode flow,
            String currentSessionCookie, String returnTo, boolean secure) {
        if (pending.consumeIdentityVerified(verified.id(), cookieHash, clock.instant()).isEmpty()) {
            return redirect(returnTo, "failed", null, secure);
        }
        var bindingResult = sessions.currentBindingIfActive(currentSessionCookie);
        if (bindingResult.isEmpty()) {
            return redirect(returnTo, "failed", null, secure);
        }
        MemberSessionService.SessionBinding binding = bindingResult.get();
        String expectedMemberId = text(flow, "memberId");
        String expectedSessionId = text(flow, "sessionId");
        if (!expectedMemberId.equals(binding.memberId()) || !expectedSessionId.equals(binding.sessionId())) {
            return redirect(returnTo, "failed", null, secure);
        }
        var target = members.findLinkTargetById(expectedMemberId);
        if (target.isEmpty() || !"active".equals(target.get().status())) {
            return redirect(returnTo, "failed", null, secure);
        }
        String provider = text(flow, "provider");
        String subject = text(flow, "providerSubject");
        var existing = identities.findByProviderSubject(provider, subject);
        if (existing.isPresent()) {
            return redirect(returnTo, expectedMemberId.equals(existing.get().memberId()) ? "linked" : "failed",
                    null, secure);
        }
        EmailAddress email = usableEmail(flow);
        if (email == null || !email.key().equals(target.get().emailKey())) {
            return redirect(returnTo, "failed", null, secure);
        }
        identities.insert(randomToken(), expectedMemberId, provider, subject, clock.instant());
        return redirect(returnTo, "linked", null, secure);
    }

    private EmailAddress usableEmail(JsonNode flow) {
        if (!flow.path("emailVerified").asBoolean()) return null;
        String raw = text(flow, "email");
        if (raw == null) return null;
        try {
            return EmailAddress.parse(raw);
        } catch (CustomException invalidEmail) {
            return null;
        }
    }

    private static String randomToken() {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private JsonNode parse(String json) {
        try { return mapper.readTree(json); }
        catch (JacksonException exception) { return null; }
    }

    private void consume(OAuthPendingRow row, String cookieHash) {
        if (pending.consumeIdentityVerified(row.id(), cookieHash, clock.instant()).isEmpty()) return;
    }

    private ResponseEntity<Void> redirect(String path, String result, String cookie, boolean secure, String... extraCookies) {
        String location = result == null ? path : path + "?social=" + result;
        var response = ResponseEntity.status(302).header(HttpHeaders.LOCATION, location);
        if (cookie != null) response.header(HttpHeaders.SET_COOKIE, cookie);
        else response.header(HttpHeaders.SET_COOKIE, clearPending(secure));
        for (String extra : extraCookies) response.header(HttpHeaders.SET_COOKIE, extra);
        return response.build();
    }

    private String clearPending(boolean secure) {
        return ResponseCookie.from(SocialAuthService.PENDING_COOKIE, "").secure(secure).httpOnly(true)
                .sameSite("Lax").path("/api/v1/auth/social").maxAge(Duration.ZERO).build().toString();
    }

    private static String text(JsonNode node, String field) {
        JsonNode value = node == null ? null : node.get(field);
        return value == null || !value.isString() ? null : value.asString();
    }

    private static String hash(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.US_ASCII)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 unavailable", exception);
        }
    }
}
