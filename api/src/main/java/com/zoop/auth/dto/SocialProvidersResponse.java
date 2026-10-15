package com.zoop.auth.dto;

import java.util.List;

public record SocialProvidersResponse(List<SocialProviderOut> items, String nextCursor) {
}
