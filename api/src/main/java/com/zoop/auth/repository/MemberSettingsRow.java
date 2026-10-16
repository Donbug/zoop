package com.zoop.auth.repository;

import java.util.List;

public record MemberSettingsRow(String mode, Boolean investor, boolean completed,
        boolean tutorialCompleted, long version, List<String> watchlistIds) {
}
