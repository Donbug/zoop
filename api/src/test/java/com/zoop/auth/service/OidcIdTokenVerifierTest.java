package com.zoop.auth.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.nio.charset.StandardCharsets;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.Signature;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.HexFormat;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;
import com.zoop.auth.config.SocialAuthSettings;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class OidcIdTokenVerifierTest {
    private static final Instant NOW = Instant.parse("2026-10-15T00:00:00Z");
    private static KeyPair keyPair;
    private ObjectMapper mapper;
    private OidcJwksProvider jwks;
    private OidcIdTokenVerifier verifier;
    private SocialAuthSettings.ProviderSettings google;

    @BeforeAll
    static void makeSigningKey() throws Exception {
        KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        keyPair = generator.generateKeyPair();
    }

    @BeforeEach
    void setUp() {
        mapper = JsonMapper.builder().build();
        jwks = mock(OidcJwksProvider.class);
        when(jwks.signingKey("google", "test-key")).thenReturn(keyPair.getPublic());
        verifier = new OidcIdTokenVerifier(jwks, Clock.fixed(NOW, ZoneOffset.UTC));
        google = new SocialAuthSettings.ProviderSettings("google", "Google", "https://accounts.google.com/o/oauth2/v2/auth",
                "client-id", "client-secret", "https://api.example.com/callback", "openid email");
    }

    @Test
    void validatesSignatureIssuerAudienceExpiryNonceAndReturnsClaims() throws Exception {
        String token = signedToken("https://accounts.google.com", "client-id", "nonce-value", NOW.plusSeconds(300));

        OidcIdTokenVerifier.VerifiedClaims claims = verifier.verify("google", google, token, hash("nonce-value"));

        assertEquals("stable-provider-subject", claims.subject());
        assertEquals("person@example.com", claims.email());
        org.junit.jupiter.api.Assertions.assertTrue(claims.emailVerified());
    }

    @Test
    void rejectsWrongSignatureAudienceExpiredTokenAndNonce() throws Exception {
        String token = signedToken("https://accounts.google.com", "client-id", "nonce-value", NOW.plusSeconds(300));
        String[] pieces = token.split("\\.");
        String wrongSignature = pieces[0] + "." + pieces[1] + "." + base64("wrong".getBytes(StandardCharsets.UTF_8));
        assertThrows(InvalidSocialAuthException.class,
                () -> verifier.verify("google", google, wrongSignature, hash("nonce-value")));
        assertThrows(InvalidSocialAuthException.class, () -> verifier.verify("google", google,
                signedToken("https://accounts.google.com", "other-client", "nonce-value", NOW.plusSeconds(300)),
                hash("nonce-value")));
        assertThrows(InvalidSocialAuthException.class, () -> verifier.verify("google", google,
                signedToken("https://accounts.google.com", "client-id", "nonce-value", NOW), hash("nonce-value")));
        assertThrows(InvalidSocialAuthException.class, () -> verifier.verify("google", google,
                token, hash("different-nonce")));
    }

    @Test
    void rejectsIssuerAndAlgorithmConfusion() throws Exception {
        assertThrows(InvalidSocialAuthException.class, () -> verifier.verify("google", google,
                signedToken("https://attacker.example", "client-id", "nonce-value", NOW.plusSeconds(300)),
                hash("nonce-value")));
        String token = signedToken("https://accounts.google.com", "client-id", "nonce-value", NOW.plusSeconds(300));
        String[] pieces = token.split("\\.");
        var header = mapper.createObjectNode().put("alg", "none").put("kid", "test-key").put("typ", "JWT");
        String encodedHeader = base64(mapper.writeValueAsBytes(header));
        String none = encodedHeader + "." + pieces[1] + "." + pieces[2];
        assertThrows(InvalidSocialAuthException.class,
                () -> verifier.verify("google", google, none, hash("nonce-value")));
    }

    @Test
    void validatesOptionalNotBeforeWithSixtySecondClockSkew() throws Exception {
        String slightlyFuture = signedToken("https://accounts.google.com", "client-id", "nonce-value",
                NOW.plusSeconds(300), mapper.getNodeFactory().numberNode(NOW.getEpochSecond() + 60));
        verifier.verify("google", google, slightlyFuture, hash("nonce-value"));

        String future = signedToken("https://accounts.google.com", "client-id", "nonce-value",
                NOW.plusSeconds(300), mapper.getNodeFactory().numberNode(NOW.getEpochSecond() + 61));
        assertThrows(InvalidSocialAuthException.class,
                () -> verifier.verify("google", google, future, hash("nonce-value")));

        String nonNumericDate = signedToken("https://accounts.google.com", "client-id", "nonce-value",
                NOW.plusSeconds(300), mapper.getNodeFactory().textNode("2026-10-15T00:00:00Z"));
        assertThrows(InvalidSocialAuthException.class,
                () -> verifier.verify("google", google, nonNumericDate, hash("nonce-value")));
    }

    private String signedToken(String issuer, String audience, String nonce, Instant expiry) throws Exception {
        return signedToken(issuer, audience, nonce, expiry, null);
    }

    private String signedToken(String issuer, String audience, String nonce, Instant expiry, JsonNode notBefore)
            throws Exception {
        var header = mapper.createObjectNode().put("alg", "RS256").put("kid", "test-key").put("typ", "JWT");
        var claims = mapper.createObjectNode()
                .put("iss", issuer).put("aud", audience)
                .put("sub", "stable-provider-subject")
                .put("iat", NOW.getEpochSecond()).put("exp", expiry.getEpochSecond())
                .put("nonce", nonce).put("email", "person@example.com").put("email_verified", true);
        if (notBefore != null) claims.set("nbf", notBefore);
        String signingInput = base64(mapper.writeValueAsBytes(header)) + "."
                + base64(mapper.writeValueAsBytes(claims));
        Signature signature = Signature.getInstance("SHA256withRSA");
        signature.initSign(keyPair.getPrivate());
        signature.update(signingInput.getBytes(StandardCharsets.US_ASCII));
        return signingInput + "." + base64(signature.sign());
    }

    private static String base64(byte[] value) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(value);
    }

    private static String hash(String value) throws Exception {
        return HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256")
                .digest(value.getBytes(StandardCharsets.UTF_8)));
    }
}
