package com.zoop.auth.dto;

import java.util.List;

/** User supplied display name and explicit service terms; identity fields come only from OAuth pending. */
public record SocialSignupRequest(String displayName, List<SignupRequest.Agreement> agreements) {
    @Override
    public String toString() {
        return "SocialSignupRequest[displayName=<redacted>, agreements="
                + (agreements == null ? "null" : agreements.size()) + "]";
    }
}
