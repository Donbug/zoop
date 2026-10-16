package com.zoop.auth.repository;

import java.util.Optional;

public interface MemberSettingsRepository {
    Optional<MemberSettingsRow> find(String memberId);

    Optional<MemberSettingsRow> findForUpdate(String memberId);

    void update(String memberId, String mode, Boolean investor, boolean completed,
            boolean tutorialCompleted, long expectedVersion, long nextVersion);

    boolean companiesExist(Iterable<String> companyIds);

    void replaceWatchlist(String memberId, Iterable<String> companyIds);
}
