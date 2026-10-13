package com.zoop.auth.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;

@Entity
@Table(name = "term_agreements")
@IdClass(TermAgreementId.class)
public class TermAgreement {
    @Id
    @Column(name = "member_id", nullable = false, columnDefinition = "text")
    private String memberId;

    @Id
    @Column(name = "term_id", nullable = false, columnDefinition = "text")
    private String termId;

    @Id
    @Column(name = "term_version", nullable = false, columnDefinition = "text")
    private String termVersion;

    @Column(name = "accepted", nullable = false)
    private boolean accepted;

    @Column(name = "accepted_at", nullable = false, columnDefinition = "timestamptz")
    private Instant acceptedAt;

    protected TermAgreement() {
    }
}
