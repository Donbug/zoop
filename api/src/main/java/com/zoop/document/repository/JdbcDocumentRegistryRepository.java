package com.zoop.document.repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcDocumentRegistryRepository implements DocumentRegistryRepository {
    private static final String INSERT_ARTICLE = """
            INSERT INTO articles (id, kind, provider, provider_key, lineage_key, current_version, access_status, created_at)
            VALUES (:id, :kind, :provider, NULL, NULL, NULL, 'available', :createdAt)
            ON CONFLICT (id) DO NOTHING
            """;
    private static final String FIND_ARTICLE = """
            SELECT id, kind, provider, current_version, access_status
            FROM articles
            WHERE id = :id
            """;
    private static final String LOCK_ARTICLE = """
            SELECT id, kind, provider, current_version, access_status
            FROM articles
            WHERE id = :id
            FOR UPDATE
            """;
    private static final String INSERT_ARTIFACT = """
            INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at)
            VALUES (:id, :kind, :storageUri, :sha256, :bytes, :mediaType, :createdAt)
            ON CONFLICT (id) DO NOTHING
            """;
    private static final String FIND_ARTIFACT = """
            SELECT id, kind, storage_uri, sha256, bytes, media_type, created_at
            FROM artifacts
            WHERE id = :id
            """;
    private static final String INSERT_VERSION = """
            INSERT INTO article_versions (article_id, version, title, publisher, url, published_at, published_date,
                                          publication_precision, raw_artifact_id, text_artifact_id, collected_at)
            VALUES (:articleId, :version, :title, :publisher, :url, :publishedAt, :publishedDate,
                    :publicationPrecision, :rawArtifactId, :textArtifactId, :collectedAt)
            ON CONFLICT (article_id, version) DO NOTHING
            """;
    private static final String FIND_VERSION = """
            SELECT article_id, version, title, publisher, url, published_at, published_date, publication_precision,
                   raw_artifact_id, text_artifact_id, collected_at
            FROM article_versions
            WHERE article_id = :articleId AND version = :version
            """;
    private static final String FIND_ARTICLE_FACTS = """
            SELECT a.id, a.kind, a.provider, a.current_version, a.access_status,
                   v.article_id, v.version, v.title, v.publisher, v.url, v.published_at, v.published_date,
                   v.publication_precision, v.raw_artifact_id, v.text_artifact_id, v.collected_at,
                   t.kind AS text_kind, t.storage_uri, t.sha256, t.bytes, t.media_type, t.created_at
            FROM articles a
            JOIN article_versions v ON v.article_id = a.id
            JOIN artifacts t ON t.id = v.text_artifact_id
            WHERE (v.article_id, v.version) IN (:identities)
            """;
    private static final int FACTS_BATCH_SIZE = 256;
    private static final String MOVE_POINTER = """
            UPDATE articles
            SET current_version = :target
            WHERE id = :id AND current_version IS NOT DISTINCT FROM CAST(:expected AS text)
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcDocumentRegistryRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public boolean insertArticleIfAbsent(String id, String kind, String provider, Instant createdAt) {
        return jdbc.update(INSERT_ARTICLE, new MapSqlParameterSource()
                .addValue("id", id)
                .addValue("kind", kind)
                .addValue("provider", provider)
                .addValue("createdAt", utc(createdAt))) == 1;
    }

    @Override
    public Optional<ArticleRow> findArticle(String id) {
        return jdbc.query(FIND_ARTICLE, new MapSqlParameterSource("id", id), (result, index) -> new ArticleRow(
                result.getString("id"),
                result.getString("kind"),
                result.getString("provider"),
                result.getString("current_version"),
                result.getString("access_status"))).stream().findFirst();
    }

    @Override
    public Optional<ArticleRow> lockArticle(String id) {
        return jdbc.query(LOCK_ARTICLE, new MapSqlParameterSource("id", id), (result, index) -> new ArticleRow(
                result.getString("id"),
                result.getString("kind"),
                result.getString("provider"),
                result.getString("current_version"),
                result.getString("access_status"))).stream().findFirst();
    }

    @Override
    public boolean insertArtifactIfAbsent(ArtifactRow row) {
        return jdbc.update(INSERT_ARTIFACT, new MapSqlParameterSource()
                .addValue("id", row.id())
                .addValue("kind", row.kind())
                .addValue("storageUri", row.storageUri())
                .addValue("sha256", row.sha256())
                .addValue("bytes", row.bytes())
                .addValue("mediaType", row.mediaType())
                .addValue("createdAt", utc(row.createdAt()))) == 1;
    }

    @Override
    public Optional<ArtifactRow> findArtifact(String id) {
        return jdbc.query(FIND_ARTIFACT, new MapSqlParameterSource("id", id), (result, index) -> new ArtifactRow(
                result.getString("id"),
                result.getString("kind"),
                result.getString("storage_uri"),
                result.getString("sha256"),
                result.getLong("bytes"),
                result.getString("media_type"),
                instant(result, "created_at"))).stream().findFirst();
    }

    @Override
    public boolean insertVersionIfAbsent(VersionRow row) {
        var parameters = new MapSqlParameterSource()
                .addValue("articleId", row.articleId())
                .addValue("version", row.version())
                .addValue("title", row.title(), Types.VARCHAR)
                .addValue("publisher", row.publisher(), Types.VARCHAR)
                .addValue("url", row.url(), Types.VARCHAR)
                .addValue("publicationPrecision", row.publicationPrecision())
                .addValue("rawArtifactId", row.rawArtifactId(), Types.VARCHAR)
                .addValue("textArtifactId", row.textArtifactId())
                .addValue("collectedAt", utc(row.collectedAt()));
        // A typed non-null value would take a driver-specific conversion path; only NULLs need the SQL type.
        if (row.publishedAt() == null) {
            parameters.addValue("publishedAt", null, Types.TIMESTAMP_WITH_TIMEZONE);
        } else {
            parameters.addValue("publishedAt", utc(row.publishedAt()));
        }
        if (row.publishedDate() == null) {
            parameters.addValue("publishedDate", null, Types.DATE);
        } else {
            parameters.addValue("publishedDate", row.publishedDate());
        }
        return jdbc.update(INSERT_VERSION, parameters) == 1;
    }

    @Override
    public Optional<VersionRow> findVersion(String articleId, String version) {
        return jdbc.query(FIND_VERSION, new MapSqlParameterSource()
                .addValue("articleId", articleId)
                .addValue("version", version), (result, index) -> new VersionRow(
                result.getString("article_id"),
                result.getString("version"),
                result.getString("title"),
                result.getString("publisher"),
                result.getString("url"),
                instant(result, "published_at"),
                result.getObject("published_date", LocalDate.class),
                result.getString("publication_precision"),
                result.getString("raw_artifact_id"),
                result.getString("text_artifact_id"),
                instant(result, "collected_at"))).stream().findFirst();
    }

    @Override
    public Map<ArticleVersion, ArticleFacts> findArticleFacts(Set<ArticleVersion> identities) {
        Map<ArticleVersion, ArticleFacts> found = new HashMap<>();
        var batch = new ArrayList<Object[]>(Math.min(identities.size(), FACTS_BATCH_SIZE));
        for (ArticleVersion identity : identities) {
            batch.add(new Object[] {identity.articleId(), identity.version()});
            if (batch.size() == FACTS_BATCH_SIZE) {
                readArticleFacts(batch, found);
                batch.clear();
            }
        }
        if (!batch.isEmpty()) readArticleFacts(batch, found);
        return found;
    }

    private void readArticleFacts(ArrayList<Object[]> batch, Map<ArticleVersion, ArticleFacts> found) {
        jdbc.query(FIND_ARTICLE_FACTS, new MapSqlParameterSource("identities", batch), result -> {
            var article = new ArticleRow(result.getString("id"), result.getString("kind"), result.getString("provider"),
                    result.getString("current_version"), result.getString("access_status"));
            var version = new VersionRow(result.getString("article_id"), result.getString("version"), result.getString("title"),
                    result.getString("publisher"), result.getString("url"), instant(result, "published_at"),
                    result.getObject("published_date", LocalDate.class), result.getString("publication_precision"),
                    result.getString("raw_artifact_id"), result.getString("text_artifact_id"), instant(result, "collected_at"));
            var text = new ArtifactRow(version.textArtifactId(), result.getString("text_kind"), result.getString("storage_uri"),
                    result.getString("sha256"), result.getLong("bytes"), result.getString("media_type"), instant(result, "created_at"));
            found.put(new ArticleVersion(article.id(), version.version()), new ArticleFacts(article, version, text));
        });
    }

    @Override
    public boolean movePointer(String articleId, String expected, String target) {
        return jdbc.update(MOVE_POINTER, new MapSqlParameterSource()
                .addValue("id", articleId)
                .addValue("expected", expected, Types.VARCHAR)
                .addValue("target", target)) == 1;
    }

    private static OffsetDateTime utc(Instant instant) {
        return OffsetDateTime.ofInstant(instant, ZoneOffset.UTC);
    }

    private static Instant instant(ResultSet result, String column) throws SQLException {
        OffsetDateTime value = result.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }
}
