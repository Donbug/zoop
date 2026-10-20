package com.zoop.document.service;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.function.Supplier;

import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.DuplicateKeyException;

/**
 * Test double with the registry's relational semantics: primary keys, the unique storage URI, foreign keys and the
 * NULL-safe compare-and-set. Spring's rollback is not simulated by the double; {@link #transactionally} reproduces the
 * transaction boundary for tests that need "an exception undoes everything the item wrote". The real SQL, constraints and
 * rollback are proven against PostgreSQL by the operator smoke and the SQL proof.
 */
public final class InMemoryDocumentRegistry implements DocumentRegistryRepository {
    private Map<String, ArticleRow> articles = new LinkedHashMap<>();
    private Map<String, ArtifactRow> artifacts = new LinkedHashMap<>();
    private Map<String, VersionRow> versions = new LinkedHashMap<>();
    private int writeAttempts;

    public record State(Map<String, ArticleRow> articles, Map<String, ArtifactRow> artifacts,
            Map<String, VersionRow> versions) {
    }

    public State state() {
        return new State(new LinkedHashMap<>(articles), new LinkedHashMap<>(artifacts), new LinkedHashMap<>(versions));
    }

    /** Runs {@code work} as one transaction: any exception restores the state from before it. */
    public <T> T transactionally(Supplier<T> work) {
        State before = state();
        try {
            return work.get();
        } catch (RuntimeException | Error failure) {
            articles = new LinkedHashMap<>(before.articles());
            artifacts = new LinkedHashMap<>(before.artifacts());
            versions = new LinkedHashMap<>(before.versions());
            throw failure;
        }
    }

    public int writeAttempts() {
        return writeAttempts;
    }

    public void seedArticle(String id, String kind, String provider, String currentVersion, String accessStatus) {
        articles.put(id, new ArticleRow(id, kind, provider, currentVersion, accessStatus));
    }

    public void setAccessStatus(String id, String accessStatus) {
        ArticleRow row = articles.get(id);
        articles.put(id, new ArticleRow(id, row.kind(), row.provider(), row.currentVersion(), accessStatus));
    }

    @Override
    public boolean insertArticleIfAbsent(String id, String kind, String provider, Instant createdAt) {
        writeAttempts++;
        if (articles.containsKey(id)) {
            return false;
        }
        articles.put(id, new ArticleRow(id, kind, provider, null, "available"));
        return true;
    }

    @Override
    public Optional<ArticleRow> findArticle(String id) {
        return Optional.ofNullable(articles.get(id));
    }

    @Override
    public Optional<ArticleRow> lockArticle(String id) {
        return Optional.ofNullable(articles.get(id));
    }

    @Override
    public boolean insertArtifactIfAbsent(ArtifactRow row) {
        writeAttempts++;
        if (artifacts.containsKey(row.id())) {
            return false;
        }
        if (artifacts.values().stream().anyMatch(other -> other.storageUri().equals(row.storageUri()))) {
            throw new DuplicateKeyException("uq_artifacts_storage_uri");
        }
        artifacts.put(row.id(), row);
        return true;
    }

    /** Test setup only (not a repository operation, not counted as a write): the row of an id as a test needs it to be. */
    public void replaceArtifact(ArtifactRow row) {
        artifacts.put(row.id(), row);
    }

    /** Test setup only: the id is no longer registered. */
    public void removeArtifact(String id) {
        artifacts.remove(id);
    }

    @Override
    public Optional<ArtifactRow> findArtifact(String id) {
        return Optional.ofNullable(artifacts.get(id));
    }

    @Override
    public boolean insertVersionIfAbsent(VersionRow row) {
        writeAttempts++;
        String key = key(row.articleId(), row.version());
        if (versions.containsKey(key)) {
            return false;
        }
        if (!articles.containsKey(row.articleId()) || !artifacts.containsKey(row.textArtifactId())) {
            throw new DataIntegrityViolationException("foreign key");
        }
        versions.put(key, row);
        return true;
    }

    @Override
    public Optional<VersionRow> findVersion(String articleId, String version) {
        return Optional.ofNullable(versions.get(key(articleId, version)));
    }

    @Override
    public boolean movePointer(String articleId, String expected, String target) {
        writeAttempts++;
        ArticleRow row = articles.get(articleId);
        if (row == null || !Objects.equals(row.currentVersion(), expected)) {
            return false;
        }
        if (!versions.containsKey(key(articleId, target))) {
            throw new DataIntegrityViolationException("foreign key");
        }
        articles.put(articleId, new ArticleRow(row.id(), row.kind(), row.provider(), target, row.accessStatus()));
        return true;
    }

    private static String key(String articleId, String version) {
        return articleId + '\u0000' + version;
    }
}
