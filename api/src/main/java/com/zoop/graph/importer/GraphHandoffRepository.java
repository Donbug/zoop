package com.zoop.graph.importer;

import java.time.Instant;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import com.zoop.document.analysis.repository.EvidenceRow;

/**
 * Primitive statements of the graph handoff import beyond the document registry (articles, versions and artifacts use
 * {@link com.zoop.document.repository.DocumentRegistryRepository}). Every method must run inside the caller's single
 * transaction; the decisions (what must match, when to fail) belong to the importer, not to the repository.
 *
 * <p>Nothing here can activate a version: there is no statement that writes {@code graph_activations}, sets
 * {@code graph_versions.active} or changes an article's current version. And nothing here repairs a row: evidence and versions
 * are inserted or left exactly as they are.
 */
public interface GraphHandoffRepository {

    /**
     * Takes the company catalog lock until the caller's transaction ends: no other transaction can insert, change or delete a
     * company row meanwhile, and this call waits for a catalog writer that holds the lock first. It must be the FIRST statement
     * of the transaction, before {@link #companies} and before any row lock, which is the order of the catalog import (table
     * lock first, then its rows), so the two can never wait on each other. It does not stop readers of the catalog.
     */
    void lockCatalog();

    /** The catalog rows of these company ids; ids without a row are simply absent from the map. */
    Map<String, CompanyRow> companies(Collection<String> ids);

    /** The COMPLETE evidence row with this id: content, kind, verification and the kind of the verification artifact. */
    Optional<StoredEvidence> findEvidence(String id);

    /**
     * Inserts one evidence row through the document analysis statement: a body citation with {@code quote_verified = TRUE}, the
     * verification artifact and time of the row. The caller has already found no row with this id.
     */
    void insertEvidence(EvidenceRow row);

    /** The version row with the snapshot artifact it points at, or empty. */
    Optional<StagedVersion> findVersion(String id);

    /**
     * The enabled publication rules with {@code rule_revision} (MAX {@code publication_rule_changes.log_revision}) and
     * {@code review_revision} (MAX {@code review_decisions.global_revision}), read by ONE statement and without the publication
     * lock: imports run every round and must never hold up a switch, a review decision or an activation. Both counters are taken
     * as MAX+1 under that lock, which is held to the commit, so one statement sees a committed prefix of each and the rules it
     * returns are exactly the state at that {@code rule_revision}. A switch committed later is the next import's.
     */
    PublicationState publicationState();

    /** The rules a staged version was filtered with, in id order; empty when it was staged with none enabled or before rules. */
    List<RuleRow> versionRules(String versionId);

    /**
     * Inserts one INACTIVE {@code snapshot} version with no publication time, its two revisions and the rules it was filtered
     * with ({@code graph_version_rules}).
     */
    void insertStagedVersion(NewStagedVersion version);

    /** One publication rule: its versioned id and its definition as stored (JSON text). */
    record RuleRow(String id, String definition) {
    }

    record PublicationState(long ruleRevision, long reviewRevision, List<RuleRow> enabledRules) {
        public PublicationState {
            enabledRules = List.copyOf(enabledRules);
        }
    }

    /** One catalog company: {@code name} is what a bundle label must equal. */
    record CompanyRow(String id, String name) {
    }

    /**
     * Every column that decides whether an existing evidence row is the row a handoff would register. {@code quoteVerified} is
     * {@code null} for an unverified row; {@code verificationKind} is the {@code artifacts.kind} of its verification artifact, or
     * {@code null} when it has none.
     */
    record StoredEvidence(EvidenceRow row, String offsetUnit, String inputKind, String summaryAnalysisId,
            Boolean quoteVerified, String verificationKind) {
    }

    /** {@code ruleRevision} is {@code null} for a version staged before rules existed (or a fixture). */
    record StagedVersion(String id, String kind, boolean active, String snapshotArtifactId, String createdBy, Long ruleRevision,
            long reviewRevision) {
    }

    /**
     * @param createdBy      {@code operator:<operator>}, from the request, never an AI review identity
     * @param reason         why the row exists (staged, not activated)
     * @param sourceLabel    the handoff id the version was imported from
     * @param policyVersion  the projection policy of the bundle
     * @param issueCount     what the stored snapshot holds after the rules, as are the other two counts
     * @param ruleRevision   {@link PublicationState#ruleRevision()} the rules were read at
     * @param reviewRevision {@link PublicationState#reviewRevision()} read with them
     * @param ruleIds        the rules the snapshot was filtered with
     */
    record NewStagedVersion(String id, String createdBy, String reason, String sourceLabel, String policyVersion,
            String snapshotArtifactId, long issueCount, long relationCount, long articleCount, Instant createdAt,
            long ruleRevision, long reviewRevision, List<String> ruleIds) {
        public NewStagedVersion {
            ruleIds = List.copyOf(ruleIds);
        }
    }
}
