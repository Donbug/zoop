package com.zoop.telemetry.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** JPA schema mapping for privacy-preserving telemetry events written through JDBC. */
@Entity
@Table(name = "telemetry_events")
public class TelemetryEvent {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false)
    private long id;

    @Column(name = "principal_key", nullable = false, columnDefinition = "text")
    private String principalKey;

    @Column(name = "event_type", nullable = false, columnDefinition = "text")
    private String eventType;

    @Column(name = "screen", columnDefinition = "text")
    private String screen;

    @Column(name = "target_id", columnDefinition = "text")
    private String targetId;

    @Column(name = "round_id", columnDefinition = "text")
    private String roundId;

    @Column(name = "view_id", nullable = false, columnDefinition = "text")
    private String viewId;

    @Column(name = "occurred_at", nullable = false, columnDefinition = "timestamptz")
    private Instant occurredAt;

    protected TelemetryEvent() {
    }
}
