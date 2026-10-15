package com.zoop.company.entity;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "companies")
public class CompanyEntity {
    @Id
    @Column(name = "id", nullable = false, columnDefinition = "text")
    private String id;

    @Column(name = "ticker", columnDefinition = "text")
    private String ticker;

    @Column(name = "exchange_code", columnDefinition = "text")
    private String exchangeCode;

    @Column(name = "name", nullable = false, columnDefinition = "text")
    private String name;

    @Column(name = "name_key", nullable = false, columnDefinition = "text")
    private String nameKey;

    @Column(name = "market", columnDefinition = "text")
    private String market;

    @JdbcTypeCode(SqlTypes.ARRAY)
    @Column(name = "aliases", nullable = false, columnDefinition = "text[]")
    private List<String> aliases;

    @Column(name = "search_text", nullable = false, columnDefinition = "text")
    private String searchText;

    @Column(name = "brand_color", columnDefinition = "text")
    private String brandColor;

    @Column(name = "logo_url", columnDefinition = "text")
    private String logoUrl;

    @Column(name = "brand_source", columnDefinition = "text")
    private String brandSource;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "profile", nullable = false, columnDefinition = "jsonb")
    private Map<String, Object> profile;

    @Column(name = "created_at", nullable = false, columnDefinition = "timestamptz")
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false, columnDefinition = "timestamptz")
    private Instant updatedAt;

    protected CompanyEntity() {
    }
}
