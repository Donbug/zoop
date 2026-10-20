package com.zoop.graph.importer;

import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Supplier;

import com.zoop.document.analysis.repository.EvidenceRow;
import org.springframework.dao.DataIntegrityViolationException;

/**
 * Test double with the relational semantics the import relies on: the evidence primary key, the version primary key and the
 * pointer columns. Spring's rollback is not simulated by the double; {@link #transactionally} reproduces the transaction
 * boundary for the tests that need "an exception undoes everything the import wrote". The real SQL, constraints, row locks and
 * rollback are proven against PostgreSQL by {@code GraphHandoffImportPostgresIntegrationTest} and the operator smoke.
 *
 * <p>{@code activeVersionId} and {@code activations} stand for the activation pointer and its history: the port has no statement
 * that can change them, so a test that seeds them and finds them unchanged proves the import never reached for them.
 */
final class InMemoryGraphHandoffRepository implements GraphHandoffRepository {
    private Map<String, CompanyRow> companies = new LinkedHashMap<>();
    private Map<String, StoredEvidence> evidence = new LinkedHashMap<>();
    private Map<String, StagedVersion> versions = new LinkedHashMap<>();
    private List<NewStagedVersion> inserted = new ArrayList<>();
    private int writes;
    /** Whether the catalog lock was taken in the current transaction: a catalog read without it is a defect of the importer. */
    private boolean catalogLocked;
    final String activeVersionId;
    final int activations;

    InMemoryGraphHandoffRepository(String activeVersionId, int activations) {
        this.activeVersionId = activeVersionId;
        this.activations = activations;
    }

    record State(Map<String, StoredEvidence> evidence, Map<String, StagedVersion> versions, List<NewStagedVersion> inserted) {
    }

    State state() {
        return new State(new LinkedHashMap<>(evidence), new LinkedHashMap<>(versions), new ArrayList<>(inserted));
    }

    /** The evidence rows as the document analysis repository reads them (content and verification columns only). */
    Map<String, EvidenceRow> evidenceRows() {
        Map<String, EvidenceRow> rows = new LinkedHashMap<>();
        evidence.forEach((id, stored) -> rows.put(id, stored.row()));
        return rows;
    }

    /** Runs {@code work} as one transaction: any exception restores the state from before it. */
    <T> T transactionally(Supplier<T> work) {
        State before = state();
        try {
            return work.get();
        } catch (RuntimeException | Error failure) {
            evidence = new LinkedHashMap<>(before.evidence());
            versions = new LinkedHashMap<>(before.versions());
            inserted = new ArrayList<>(before.inserted());
            throw failure;
        } finally {
            catalogLocked = false;
        }
    }

    int writes() {
        return writes;
    }

    void seedCompany(String id, String name) {
        companies.put(id, new CompanyRow(id, name));
    }

    /**
     * A row exactly as this importer's own insert produces it when it carries a verification (a verified body citation whose
     * verification artifact is a graph receipt), or an UNVERIFIED body citation (quote_verified NULL) when it carries none.
     */
    void seedEvidence(EvidenceRow row) {
        boolean verified = row.verificationArtifactId() != null;
        evidence.put(row.id(), new StoredEvidence(row, "unicode_code_point", "body", null, verified ? Boolean.TRUE : null,
                verified ? "verification_receipt" : null));
    }

    void seedEvidence(StoredEvidence row) {
        evidence.put(row.row().id(), row);
    }

    List<NewStagedVersion> inserted() {
        return inserted;
    }

    @Override
    public void lockCatalog() {
        catalogLocked = true;
    }

    @Override
    public Map<String, CompanyRow> companies(Collection<String> ids) {
        if (!catalogLocked) {
            throw new IllegalStateException("company catalog read without the catalog lock");
        }
        Map<String, CompanyRow> found = new HashMap<>();
        for (String id : ids) {
            if (companies.containsKey(id)) {
                found.put(id, companies.get(id));
            }
        }
        return found;
    }

    @Override
    public Optional<StoredEvidence> findEvidence(String id) {
        return Optional.ofNullable(evidence.get(id));
    }

    @Override
    public void insertEvidence(EvidenceRow row) {
        writes++;
        if (evidence.containsKey(row.id())) {
            throw new DataIntegrityViolationException("evidence primary key");
        }
        // What the analysis repository's INSERT writes: a body citation, quote_verified TRUE, the verification artifact and time.
        evidence.put(row.id(), new StoredEvidence(row, "unicode_code_point", "body", null, Boolean.TRUE, "verification_receipt"));
    }

    @Override
    public Optional<StagedVersion> findVersion(String id) {
        return Optional.ofNullable(versions.get(id));
    }

    @Override
    public void insertStagedVersion(NewStagedVersion version) {
        writes++;
        if (versions.containsKey(version.id())) {
            throw new DataIntegrityViolationException("graph_versions primary key");
        }
        versions.put(version.id(), new StagedVersion(version.id(), "snapshot", false, version.snapshotArtifactId(),
                version.createdBy()));
        inserted.add(version);
    }
}
