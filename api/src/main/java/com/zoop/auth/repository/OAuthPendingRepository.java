package com.zoop.auth.repository;

import java.time.Instant;
import java.util.Optional;

/** Persistence primitives for browser-bound, one-time OAuth flows. */
public interface OAuthPendingRepository {
    void insert(String id, String cookieTokenHash, String authFlowJson, Instant createdAt, Instant expiresAt);

    /** Atomically claims an unexpired authorization callback matching the browser, state hash, and provider. */
    Optional<OAuthPendingRow> claimAuthorization(String cookieTokenHash, String stateHash,
            String provider, Instant now);

    /** Stores only verified provider identity claims and disables callback replay. */
    Optional<OAuthPendingRow> completeVerification(String id, String cookieTokenHash,
            String authFlowJson, Instant now);

    /** Rotates the pending cookie and changes the claimed flow into a signup-consent flow. */
    Optional<OAuthPendingRow> rotateToConsent(String id, String previousTokenHash,
            String nextTokenHash, String authFlowJson, Instant now, Instant expiresAt);

    /** Atomically consumes a consent-pending browser flow. Call inside the signup transaction. */
    Optional<OAuthPendingRow> consumeConsent(String cookieTokenHash, Instant now);

    /** Atomically consumes a verified identity after the callback has been classified. */
    Optional<OAuthPendingRow> consumeIdentityVerified(String id, String cookieTokenHash, Instant now);

    /** Deletes an unexpired callback-claimed flow after login/link completion or a failed callback. */
    boolean consumeClaimedCallback(String id, String cookieTokenHash, Instant now);

    /** Removes any previous pending flow carried by this browser before a new flow is created. */
    void deleteByTokenHash(String cookieTokenHash);

    int purgeExpired(Instant before);
}
