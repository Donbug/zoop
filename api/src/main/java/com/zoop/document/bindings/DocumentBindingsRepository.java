package com.zoop.document.bindings;

import java.util.Collection;
import java.util.List;
import java.util.Map;

import com.zoop.document.bindings.BindingSelection.VersionKey;

/**
 * The reads the bindings export needs over the registry: article versions joined with their article and their text artifact.
 * Every method is a plain read, takes no lock and writes nothing; the order of the rows is the caller's business.
 */
public interface DocumentBindingsRepository {

    /** Every registered article version, or only those of articles whose {@code access_status} is {@code available}. */
    List<BindingRow> listVersions(boolean availableOnly);

    /** How many registered versions belong to articles that are NOT {@code available}, per access status (empty when none). */
    Map<String, Integer> countExcludedByStatus();

    /** The registered rows of exactly these versions, whatever their article's status; a version without a row is simply absent. */
    List<BindingRow> findVersions(Collection<VersionKey> keys);

    /**
     * One registered article version as the export sees it.
     *
     * @param articleId      {@code article_versions.article_id} (the S2-1 document id, {@code doc-} + SHA-256)
     * @param version        {@code article_versions.version} (the S2-1 document version)
     * @param textArtifactId {@code article_versions.text_artifact_id} ({@code text-} + the document version)
     * @param accessStatus   {@code articles.access_status}
     * @param artifactKind   {@code artifacts.kind} of the text artifact
     * @param textSha256     {@code artifacts.sha256} of the text artifact: the SHA-256 of the stored UTF-8 text
     */
    record BindingRow(String articleId, String version, String textArtifactId, String accessStatus, String artifactKind,
            String textSha256) {
    }
}
