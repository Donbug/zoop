package com.zoop.graph.read;

import java.util.Set;

/**
 * Items that are publicly excluded right now (rights withdrawn, mislinks), applied to every version including past
 * ones. This is the app's current decision overlay; it is not the asOf filter and does not change any snapshot.
 * {@code revision} is the app decision revision it was read at (kept apart from AI source/review revisions).
 */
public record DisclosureExclusions(long revision, Set<String> issueIds, Set<String> relationIds,
        Set<String> evidenceIds, Set<ArticleTarget> articleTargets) {
    /** One article version in the version-scoped exclusion overlay. */
    public record ArticleTarget(String articleId, String articleVersion) { }

    public static final DisclosureExclusions NONE = new DisclosureExclusions(0, Set.of(), Set.of(), Set.of(), Set.of());

    /** Compatibility constructor for graph consumers that do not use article targets directly. */
    public DisclosureExclusions(long revision, Set<String> issueIds, Set<String> relationIds, Set<String> evidenceIds) {
        this(revision, issueIds, relationIds, evidenceIds, Set.of());
    }

    public DisclosureExclusions {
        issueIds = Set.copyOf(issueIds);
        relationIds = Set.copyOf(relationIds);
        evidenceIds = Set.copyOf(evidenceIds);
        articleTargets = Set.copyOf(articleTargets);
    }
}
