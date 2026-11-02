package com.zoop.graph.publication;

import java.util.ArrayList;
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
import tools.jackson.databind.node.ObjectNode;

/**
 * Prepares the next inactive candidate on top of the active publication (#55, automatic preparation): picks the imported native
 * sources not yet published, proposes the decisions {@link PublicationMerger#propose} can make and runs the same
 * {@link GraphPublicationComposer} an operator runs with the request it built. It never activates; publishing stays a person's
 * approval and manual CAS. The first real publication (nothing or a fixture active) is an operator compose.
 *
 * <p>Rerunning after an unknown outcome is safe: the same inputs make the same composition, which the composer answers
 * {@code unchanged} when it was committed.
 */
public final class GraphPublicationPreparer {
    public static final String RESULT_SCHEMA = "zoop-graph-publication-prepare-result-1";
    static final int MAX_INCOMING = 20;

    private final GraphVersionRepository versions;
    private final GraphHandoffRepository graph;
    private final JdbcGraphPublicationRepository publications;
    private final GraphPublicationReader reader;
    private final GraphPublicationComposer composer;
    private final String operator;

    public GraphPublicationPreparer(GraphVersionRepository versions, GraphHandoffRepository graph, JdbcGraphPublicationRepository publications,
            GraphPublicationReader reader, GraphPublicationComposer composer, String operator) {
        this.versions = versions; this.graph = graph; this.publications = publications;
        this.reader = reader; this.composer = composer; this.operator = operator;
    }

    public ObjectNode run() {
        ObjectNode result = StrictJson.newObject(); result.put("schemaVersion", RESULT_SCHEMA);
        try {
            var active = versions.active().orElse(null);
            result.put("activeVersionId", active == null ? null : active.id());
            if (active == null || "fixture".equals(active.kind())) return failed(result, "first_publication_manual");
            Publication base = reader.read(active.id());
            Set<String> members = base.contributions().stream().map(Contribution::sourceVersionId).collect(Collectors.toSet());
            List<Contribution> incoming = new ArrayList<>();
            for (String id : publications.preparationCandidates(members)) {
                if (incoming.size() == MAX_INCOMING) break;
                Publication candidate = reader.read(id);
                if (candidate.composed() || candidate.contributions().size() != 1) continue;
                Contribution source = candidate.contributions().getFirst();
                if ("native".equals(source.sourceKind())) incoming.add(source);
            }
            var incomingIds = result.putArray("incomingVersionIds");
            incoming.forEach(c -> incomingIds.add(c.sourceVersionId()));
            if (incoming.isEmpty()) { result.put("status", "succeeded"); result.put("outcome", "nothing_to_prepare"); return result; }
            List<Contribution> all = new ArrayList<>(base.contributions()); all.addAll(incoming);
            var proposal = PublicationMerger.propose(all, base.effectiveDecisions(), base.issueSources(),
                    new PublicationMerger.Automatic(incoming.stream().map(Contribution::sourceVersionId).toList()));
            byte[] decisions = Canonical.bytes(proposal.decisions().node());
            var pins = new TreeMap<String, String>();
            incoming.forEach(c -> pins.put(c.sourceVersionId(), c.receipt().sha256()));
            var state = graph.publicationState();
            var request = new PublicationComposeRequest(active.id(), List.copyOf(pins.keySet()), active.id(), base.receipt().sha256(), pins,
                    state.ruleRevision(), state.reviewRevision(), Canonical.sha256(decisions), operator);
            // Kept so a person can rerun the same request as an operator compose, or edit the decisions on a stop.
            result.set("request", request.wire());
            result.set("decisions", proposal.decisions().node());
            result.set("autoResolutions", GraphPublicationReader.json(proposal.resolutions()));
            ObjectNode composed = composer.run(request, decisions);
            result.set("compose", composed);
            if (!"succeeded".equals(composed.get("status").asString())) return failed(result, composed.get("code").asString());
            result.put("status", "succeeded"); result.put("outcome", composed.get("outcome").asString());
            result.put("graphVersionId", composed.get("graphVersionId").asString());
            result.put("receiptSha256", composed.get("receiptSha256").asString());
            return result;
        } catch (PublicationException failure) {
            return failed(result, failure.code());
        } catch (DataAccessException failure) {
            return failed(result, "database_unavailable");
        }
    }

    private static ObjectNode failed(ObjectNode result, String code) {
        result.put("status", "failed"); result.put("code", code);
        return result;
    }
}
