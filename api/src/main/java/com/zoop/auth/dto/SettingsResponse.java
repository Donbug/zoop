package com.zoop.auth.dto;

import java.util.List;

import com.zoop.common.response.Metadata;

public record SettingsResponse(String mode, List<String> watchlistIds, boolean tutorialCompleted,
        boolean completed, Boolean investor, long version, Metadata metadata) {
}
