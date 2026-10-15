package com.zoop.auth.service;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

import tools.jackson.databind.JsonNode;
import com.zoop.auth.config.SocialAuthSettings;
import com.zoop.auth.config.SocialAuthSettings.ProviderSettings;
import com.zoop.common.json.StrictJson;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.stereotype.Component;

/** Server-to-server OAuth requests use fixed provider hosts, no redirects, and bounded response bodies. */
@Component
final class HttpSocialProviderGateway implements SocialProviderGateway {
    private static final int MAX_BODY_BYTES = 1_048_576;
    private final SocialAuthSettings settings;
    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .followRedirects(HttpClient.Redirect.NEVER)
            .proxy(HttpClient.Builder.NO_PROXY)
            .connectTimeout(Duration.ofSeconds(4))
            .build();

    HttpSocialProviderGateway(SocialAuthSettings settings) {
        this.settings = settings;
    }

    @Override
    public TokenSet exchange(String providerId, String code, String redirectUri, String codeVerifier) {
        ProviderSettings provider = settings.provider(providerId);
        if (!settings.providerConfigured(provider)) {
            throw unavailable();
        }
        String endpoint = "google".equals(providerId)
                ? "https://oauth2.googleapis.com/token" : "https://kauth.kakao.com/oauth/token";
        String body = form("grant_type", "authorization_code")
                + "&" + form("client_id", provider.clientId())
                + "&" + form("client_secret", provider.clientSecret())
                + "&" + form("code", code)
                + "&" + form("redirect_uri", redirectUri)
                + "&" + form("code_verifier", codeVerifier);
        JsonNode response = postJson(endpoint, body, "application/x-www-form-urlencoded;charset=UTF-8");
        String accessToken = text(response, "access_token");
        String idToken = text(response, "id_token");
        if (accessToken == null || accessToken.length() > 8192
                || idToken == null || idToken.length() > 32768) {
            throw new InvalidSocialAuthException();
        }
        return new TokenSet(accessToken, idToken);
    }

    @Override
    public JsonNode kakaoUserInfo(String accessToken) {
        HttpRequest request = HttpRequest.newBuilder(URI.create("https://kapi.kakao.com/v2/user/me"))
                .timeout(Duration.ofSeconds(6))
                .header("Accept", "application/json")
                .header("Authorization", "Bearer " + accessToken)
                .GET().build();
        return sendJson(request);
    }

    private JsonNode postJson(String endpoint, String body, String contentType) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(endpoint))
                .timeout(Duration.ofSeconds(6))
                .header("Accept", "application/json")
                .header("Content-Type", contentType)
                .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8)).build();
        return sendJson(request);
    }

    private JsonNode sendJson(HttpRequest request) {
        try {
            HttpResponse<byte[]> response = http.send(request, HttpResponse.BodyHandlers.ofByteArray());
            byte[] body = response.body();
            if (body.length > MAX_BODY_BYTES) {
                throw new InvalidSocialAuthException();
            }
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                if (response.statusCode() >= 500 || response.statusCode() == 429) throw unavailable();
                throw new InvalidSocialAuthException();
            }
            try {
                return StrictJson.parseObject(body).node();
            } catch (StrictJson.Malformed exception) {
                throw new InvalidSocialAuthException();
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw unavailable();
        } catch (IOException exception) {
            throw unavailable();
        }
    }

    private static String text(JsonNode object, String key) {
        JsonNode value = object.get(key);
        return value == null || !value.isString() ? null : value.asString();
    }

    private static String form(String key, String value) {
        return URLEncoder.encode(key, StandardCharsets.UTF_8) + "="
                + URLEncoder.encode(value, StandardCharsets.UTF_8);
    }

    private static CustomException unavailable() {
        return new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
    }
}
