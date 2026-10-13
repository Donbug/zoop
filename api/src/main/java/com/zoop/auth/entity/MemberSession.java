package com.zoop.auth.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "member_sessions")
public class MemberSession {
    @Id
    @Column(name = "id", nullable = false, columnDefinition = "text")
    private String id;

    @Column(name = "member_id", columnDefinition = "text")
    private String memberId;

    @Column(name = "kind", nullable = false, columnDefinition = "text")
    private String kind;

    @Column(name = "analytics_key", columnDefinition = "text")
    private String analyticsKey;

    @Column(name = "token_hash", nullable = false, columnDefinition = "text")
    private String tokenHash;

    @Column(name = "csrf_key_id", nullable = false, columnDefinition = "text")
    private String csrfKeyId;

    @Column(name = "csrf_version", nullable = false)
    private long csrfVersion;

    @Column(name = "tutorial_completed", nullable = false)
    private boolean tutorialCompleted;

    @Column(name = "created_at", nullable = false, columnDefinition = "timestamptz")
    private Instant createdAt;

    @Column(name = "expires_at", nullable = false, columnDefinition = "timestamptz")
    private Instant expiresAt;

    @Column(name = "revoked_at", columnDefinition = "timestamptz")
    private Instant revokedAt;

    protected MemberSession() {
    }
}
