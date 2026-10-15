package com.zoop.auth.service;

import java.io.IOException;
import java.math.BigInteger;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.security.PublicKey;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.RSAPublicKeySpec;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import tools.jackson.databind.JsonNode;
import com.zoop.common.json.StrictJson;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.stereotype.Component;

@Component
final class OidcJwksProvider {
    private static final Map<String, String> JWKS_URIS = Map.of(
            "google", "https://www.googleapis.com/oauth2/v3/certs",
            "kakao", "https://kauth.kakao.com/.well-known/jwks.json");
    private static final int MAX_BODY_BYTES = 1_048_576;
    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .followRedirects(HttpClient.Redirect.NEVER)
            .proxy(HttpClient.Builder.NO_PROXY)
            .connectTimeout(Duration.ofSeconds(4))
            .build();
    private final Map<String, CachedKeys> cache = new ConcurrentHashMap<>();

    OidcJwksProvider() { }

    synchronized PublicKey signingKey(String provider, String kid) {
        if (!JWKS_URIS.containsKey(provider) || kid == null || kid.isBlank() || kid.length() > 256) {
            throw new InvalidSocialAuthException();
        }
        CachedKeys keys = cache.get(provider);
        Instant now = Instant.now();
        if (keys == null || keys.expiresAt().isBefore(now)
                || (!keys.keys().containsKey(kid)
                    && keys.loadedAt().plus(Duration.ofMinutes(1)).isBefore(now))) {
            keys = load(provider);
            cache.put(provider, keys);
        }
        PublicKey key = keys.keys().get(kid);
        if (key == null) throw new InvalidSocialAuthException();
        return key;
    }

    private CachedKeys load(String provider) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(JWKS_URIS.get(provider)))
                .timeout(Duration.ofSeconds(6)).header("Accept", "application/json").GET().build();
        try {
            HttpResponse<byte[]> response = http.send(request, HttpResponse.BodyHandlers.ofByteArray());
            byte[] body = response.body();
            if (response.statusCode() != 200 || body.length > MAX_BODY_BYTES) throw unavailable();
            JsonNode root;
            try {
                root = StrictJson.parseObject(body).node();
            } catch (StrictJson.Malformed exception) {
                throw unavailable();
            }
            JsonNode list = root == null ? null : root.get("keys");
            if (list == null || !list.isArray() || list.size() == 0 || list.size() > 100) throw unavailable();
            Map<String, PublicKey> keys = new java.util.HashMap<>();
            for (JsonNode jwk : list) {
                if (!"RSA".equals(string(jwk, "kty")) || !"RS256".equals(string(jwk, "alg"))
                        || !"sig".equals(string(jwk, "use"))) continue;
                String keyId = string(jwk, "kid");
                String modulus = string(jwk, "n");
                String exponent = string(jwk, "e");
                if (keyId == null || keyId.length() > 256 || modulus == null || exponent == null) continue;
                try {
                    BigInteger n = new BigInteger(1, Base64.getUrlDecoder().decode(modulus));
                    BigInteger e = new BigInteger(1, Base64.getUrlDecoder().decode(exponent));
                    if (n.bitLength() < 2048 || e.signum() <= 0) continue;
                    PublicKey key = java.security.KeyFactory.getInstance("RSA")
                            .generatePublic(new RSAPublicKeySpec(n, e));
                    if (key instanceof RSAPublicKey) keys.put(keyId, key);
                } catch (Exception ignored) {
                    // Ignore malformed keys; a matching valid signing key is still required.
                }
            }
            if (keys.isEmpty()) throw unavailable();
            Instant loadedAt = Instant.now();
            return new CachedKeys(Map.copyOf(keys), loadedAt, loadedAt.plus(Duration.ofMinutes(15)));
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw unavailable();
        } catch (IOException exception) {
            throw unavailable();
        }
    }

    private static String string(JsonNode object, String key) {
        JsonNode value = object.get(key);
        return value == null || !value.isString() ? null : value.asString();
    }

    private static CustomException unavailable() {
        return new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
    }

    private record CachedKeys(Map<String, PublicKey> keys, Instant loadedAt, Instant expiresAt) { }
}
