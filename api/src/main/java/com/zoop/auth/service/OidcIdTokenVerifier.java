package com.zoop.auth.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.Signature;
import java.time.Clock;
import java.time.Duration;
import java.util.Base64;
import java.util.HexFormat;

import tools.jackson.databind.JsonNode;
import com.zoop.auth.config.SocialAuthSettings.ProviderSettings;
import com.zoop.common.json.StrictJson;
import org.springframework.stereotype.Component;

@Component
final class OidcIdTokenVerifier {
    private static final long MAX_FUTURE_IAT_SECONDS = 60;
    private final OidcJwksProvider jwks;
    private final Clock clock;

    OidcIdTokenVerifier(OidcJwksProvider jwks, Clock clock) {
        this.jwks = jwks;
        this.clock = clock;
    }

    VerifiedClaims verify(String provider, ProviderSettings configuration, String idToken,
            String expectedNonceHash) {
        try {
            if (idToken == null || idToken.length() > 32768 || expectedNonceHash == null
                    || !expectedNonceHash.matches("[0-9a-f]{64}")) throw invalid();
            String[] parts = idToken.split("\\.", -1);
            if (parts.length != 3 || parts[0].length() > 4096 || parts[1].length() > 16384
                    || parts[2].length() > 4096) throw invalid();
            JsonNode header = StrictJson.parseObject(decode(parts[0])).node();
            JsonNode claims = StrictJson.parseObject(decode(parts[1])).node();
            if (!"RS256".equals(text(header, "alg"))
                    || (text(header, "typ") != null && !"JWT".equals(text(header, "typ")))) {
                throw invalid();
            }
            var key = jwks.signingKey(provider, text(header, "kid"));
            Signature signature = Signature.getInstance("SHA256withRSA");
            signature.initVerify(key);
            signature.update((parts[0] + "." + parts[1]).getBytes(StandardCharsets.US_ASCII));
            if (!signature.verify(Base64.getUrlDecoder().decode(parts[2]))) throw invalid();

            String issuer = text(claims, "iss");
            boolean validIssuer = "kakao".equals(provider)
                    ? "https://kauth.kakao.com".equals(issuer)
                    : "https://accounts.google.com".equals(issuer) || "accounts.google.com".equals(issuer);
            if (!validIssuer || !audienceContains(claims.get("aud"), configuration.clientId())) throw invalid();
            String authorizedParty = text(claims, "azp");
            JsonNode audience = claims.get("aud");
            if (authorizedParty != null && !configuration.clientId().equals(authorizedParty)
                    || audience != null && audience.isArray() && audience.size() > 1
                        && !configuration.clientId().equals(authorizedParty)) throw invalid();

            long now = clock.instant().getEpochSecond();
            JsonNode expires = claims.get("exp");
            JsonNode issued = claims.get("iat");
            if (expires == null || !expires.isIntegralNumber() || expires.asLong() <= now
                    || issued == null || !issued.isIntegralNumber() || issued.asLong() > now + MAX_FUTURE_IAT_SECONDS
                    || Duration.between(java.time.Instant.ofEpochSecond(issued.asLong()), clock.instant())
                            .compareTo(Duration.ofHours(24)) > 0) throw invalid();

            String subject = text(claims, "sub");
            String nonce = text(claims, "nonce");
            if (subject == null || subject.isBlank() || subject.length() > 512
                    || subject.chars().anyMatch(Character::isISOControl)
                    || nonce == null || !MessageDigest.isEqual(hash(nonce).getBytes(StandardCharsets.US_ASCII),
                            expectedNonceHash.getBytes(StandardCharsets.US_ASCII))) throw invalid();

            return new VerifiedClaims(subject, text(claims, "email"), bool(claims.get("email_verified")));
        } catch (InvalidSocialAuthException exception) {
            throw exception;
        } catch (Exception exception) {
            throw invalid();
        }
    }

    private static boolean audienceContains(JsonNode aud, String clientId) {
        if (aud == null) return false;
        if (aud.isString()) return clientId.equals(aud.asString());
        if (!aud.isArray()) return false;
        for (JsonNode value : aud) if (value.isString() && clientId.equals(value.asString())) return true;
        return false;
    }

    private static String text(JsonNode object, String key) {
        JsonNode value = object.get(key);
        return value == null || !value.isString() ? null : value.asString();
    }

    private static boolean bool(JsonNode value) {
        return value != null && value.isBoolean() && value.asBoolean();
    }

    private static byte[] decode(String value) {
        if (value.isEmpty() || value.contains("=")) throw invalid();
        return Base64.getUrlDecoder().decode(value);
    }

    private static String hash(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 unavailable", exception);
        }
    }

    private static InvalidSocialAuthException invalid() {
        return new InvalidSocialAuthException();
    }

    record VerifiedClaims(String subject, String email, boolean emailVerified) { }
}
