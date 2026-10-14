package com.zoop.auth.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "members")
public class Member {
    @Id
    @Column(name = "id", nullable = false, columnDefinition = "text")
    private String id;

    @Column(name = "analytics_key", nullable = false, columnDefinition = "text")
    private String analyticsKey;

    @Column(name = "email", nullable = false, columnDefinition = "text")
    private String email;

    @Column(name = "email_key", nullable = false, columnDefinition = "text")
    private String emailKey;

    @Column(name = "display_name", nullable = false, columnDefinition = "text")
    private String displayName;

    @Column(name = "password_hash", columnDefinition = "text")
    private String passwordHash;

    @Column(name = "signup_method", nullable = false, columnDefinition = "text")
    private String signupMethod;

    @Column(name = "status", nullable = false, columnDefinition = "text")
    private String status;

    @Column(name = "mode", columnDefinition = "text")
    private String mode;

    @Column(name = "investor")
    private Boolean investor;

    @Column(name = "completed", nullable = false)
    private boolean completed;

    @Column(name = "tutorial_completed", nullable = false)
    private boolean tutorialCompleted;

    @Column(name = "settings_version", nullable = false)
    private long settingsVersion;

    @Column(name = "created_at", nullable = false, columnDefinition = "timestamptz")
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false, columnDefinition = "timestamptz")
    private Instant updatedAt;

    @Column(name = "blocked_at", columnDefinition = "timestamptz")
    private Instant blockedAt;

    protected Member() {
    }
}
