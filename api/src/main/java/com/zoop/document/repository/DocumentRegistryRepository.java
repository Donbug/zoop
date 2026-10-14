package com.zoop.document.repository;

import java.time.Instant;
import java.util.Optional;

/**
 * Primitive statements of the document registry. Every method must run inside the caller's single transaction; the
 * decisions (what must match, when to fail) are the service's, not the repository's.
 */
public interface DocumentRegistryRepository {

    /** Inserts an {@code available} article without provider key or lineage unless the id exists; true when inserted. */
    boolean insertArticleIfAbsent(String id, String kind, String provider, Instant createdAt);

    /** Reads the article row without a lock (a snapshot for decisions that are re-checked under {@link #lockArticle}). */
    Optional<ArticleRow> findArticle(String id);

    /** Reads the article row under {@code FOR UPDATE}; the lock is held until the transaction ends. */
    Optional<ArticleRow> lockArticle(String id);

    /** Inserts unless the id exists (a different row holding the same storage URI is a duplicate-key error). */
    boolean insertArtifactIfAbsent(ArtifactRow row);

    Optional<ArtifactRow> findArtifact(String id);

    /** Inserts unless (article_id, version) exists; an existing row is never modified. */
    boolean insertVersionIfAbsent(VersionRow row);

    Optional<VersionRow> findVersion(String articleId, String version);

    /**
     * Compare-and-set of {@code current_version}: moves it to {@code target} only when it currently equals
     * {@code expected} (NULL-safe, so a null expected matches an unset pointer). True when a row was changed.
     */
    boolean movePointer(String articleId, String expected, String target);
}
