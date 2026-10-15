package com.zoop.auth.service;

import tools.jackson.databind.JsonNode;

interface SocialProviderGateway {
    TokenSet exchange(String provider, String code, String redirectUri, String codeVerifier);

    JsonNode kakaoUserInfo(String accessToken);

    record TokenSet(String accessToken, String idToken) {
    }
}
