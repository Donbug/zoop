package com.zoop.auth.entity;

import java.time.Instant;
import java.util.Map;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

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

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "auth_flow", columnDefinition = "jsonb")
    private Map<String, Object> authFlow;

    @Column(name = "created_at", nullable = false, columnDefinition = "timestamptz")
    private Instant createdAt;

    @Column(name = "expires_at", nullable = false, columnDefinition = "timestamptz")
    private Instant expiresAt;

    @Column(name = "revoked_at", columnDefinition = "timestamptz")
    private Instant revokedAt;

    protected MemberSession() {
    }
}
