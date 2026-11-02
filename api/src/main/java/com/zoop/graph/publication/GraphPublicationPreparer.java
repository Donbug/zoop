package com.zoop.graph.publication;

import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Set;
import java.util.TreeMap;
import java.util.stream.Collectors;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.zoop.graph.publication.GraphPublicationReader.Contribution;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.version.GraphVersionRepository;
import org.springframework.dao.DataAccessException;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Prepares the next inactive candidate on top of the active publication (#55, automatic preparation): picks the imported native
 * sources not yet published ({@link JdbcGraphPublicationRepository#preparationCandidates}), proposes the decisions
 * {@link PublicationMerger#propose} can make and runs the same {@link GraphPublicationComposer} an operator runs with the request it
 * built. It never activates; publishing stays a person's approval and manual CAS. The first real publication (nothing or a fixture
 * active) is an operator compose.
 *
 * <p>Only sources whose values agree with what is published are composed: {@link PublicationMerger.Proposal#changes()} (a headline value
 * or relation record the sources disagree on) stops the run with {@code correction_required} before composing, and people decide those
 * with an operator compose started from the result's request. Every result past source selection keeps the fixed inputs: the request
 * document, the decision bytes ({@code decisionsBase64}) and their sha256. After {@code outcome_unknown}, recover by running an operator
 * compose with exactly those inputs (the composer answers {@code unchanged} when it was committed); running the preparation again is a
 * new preparation, which picks base, sources and revisions afresh. {@code pendingCandidates} lists every candidate on the same base
 * that was never made public.
 */
public final class GraphPublicationPreparer {
    public static final String RESULT_SCHEMA = "zoop-graph-publication-prepare-result-1";
    /** The compose request operator of a preparation; reserved, so its staged versions are recognisable. */
    public static final String OPERATOR = "graph-publication-prepare";
    static final int MAX_INCOMING = 20;

    private final GraphVersionRepository versions;
    private final GraphHandoffRepository graph;
    private final JdbcGraphPublicationRepository publications;
    private final GraphPublicationReader reader;
    private final GraphPublicationComposer composer;

    public GraphPublicationPreparer(GraphVersionRepository versions, GraphHandoffRepository graph, JdbcGraphPublicationRepository publications,
            GraphPublicationReader reader, GraphPublicationComposer composer) {
        this.versions = versions; this.graph = graph; this.publications = publications;
        this.reader = reader; this.composer = composer;
    }

    public ObjectNode run() {
        ObjectNode result = StrictJson.newObject(); result.put("schemaVersion", RESULT_SCHEMA);
        ArrayNode incomingIds = result.putArray("incomingVersionIds");
        String reading = null;
        try {
            var active = versions.active().orElse(null);
            result.put("activeVersionId", active == null ? null : active.id());
            if (active == null || "fixture".equals(active.kind())) return failed(result, "first_publication_manual");
            reading = active.id();
            Publication base = reader.read(active.id());
            Set<String> members = base.contributions().stream().map(Contribution::sourceVersionId).collect(Collectors.toSet());
            List<Contribution> incoming = new ArrayList<>();
            for (String id : publications.preparationCandidates(active.id(), members, MAX_INCOMING)) {
                reading = id;
                Contribution source = reader.read(id).contributions().getFirst();
                if (!"native".equals(source.sourceKind())) return failed(result, "basis_mismatch", id);
                incoming.add(source); incomingIds.add(id);
            }
            reading = null;
            result.set("pendingCandidates", GraphPublicationReader.json(publications.unpublishedCandidates(active.id())));
            if (incoming.isEmpty()) { result.put("status", "succeeded"); result.put("outcome", "nothing_to_prepare"); return result; }
            List<Contribution> all = new ArrayList<>(base.contributions()); all.addAll(incoming);
            var proposal = PublicationMerger.propose(all, base.effectiveDecisions(), base.issueSources(),
                    new PublicationMerger.Automatic(incoming.stream().map(Contribution::sourceVersionId).toList()));
            byte[] decisions = Canonical.bytes(proposal.decisions().node());
            var pins = new TreeMap<String, String>();
            incoming.forEach(c -> pins.put(c.sourceVersionId(), c.receipt().sha256()));
            var state = graph.publicationState();
            var request = new PublicationComposeRequest(active.id(), List.copyOf(pins.keySet()), active.id(), base.receipt().sha256(), pins,
                    state.ruleRevision(), state.reviewRevision(), Canonical.sha256(decisions), OPERATOR);
            result.set("request", request.wire());
            result.set("decisions", proposal.decisions().node());
            result.put("decisionsBase64", Base64.getEncoder().encodeToString(decisions));
            result.put("decisionsSha256", request.decisionsSha256());
            result.set("sameHeadlines", GraphPublicationReader.json(proposal.sameHeadlines()));
            result.set("changes", GraphPublicationReader.json(proposal.changes()));
            // A changed value is never chosen by the preparation: people decide it with an operator compose (11-02 AI reply).
            if (!proposal.changes().isEmpty()) return failed(result, "correction_required");
            ObjectNode composed = composer.run(request, decisions);
            result.set("compose", composed);
            if (!"succeeded".equals(composed.get("status").asString())) return failed(result, composed.get("code").asString());
            result.put("status", "succeeded"); result.put("outcome", composed.get("outcome").asString());
            result.put("graphVersionId", composed.get("graphVersionId").asString());
            result.put("receiptSha256", composed.get("receiptSha256").asString());
            return result;
        } catch (PublicationException failure) {
            return failed(result, failure.code(), reading);
        } catch (DataAccessException failure) {
            return failed(result, "database_unavailable", reading);
        } catch (RuntimeException unexpected) {
            return failed(result, "internal_error", reading);
        }
    }

    private static ObjectNode failed(ObjectNode result, String code) {
        return failed(result, code, null);
    }

    /** {@code versionId} names the version being read when the run stopped, so a person can see which source blocks preparation. */
    private static ObjectNode failed(ObjectNode result, String code, String versionId) {
        result.put("status", "failed"); result.put("code", code);
        if (versionId != null) result.put("versionId", versionId);
        return result;
    }
}
