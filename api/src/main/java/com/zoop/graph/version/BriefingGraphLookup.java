package com.zoop.graph.version;

import java.time.Instant;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Published briefing owner resolves its immutable basis; the graph owner never guesses a current version. */
@FunctionalInterface
public interface BriefingGraphLookup {
    Basis resolve(String roundId, String requestId);

    record Reconstruction(GraphVersionRecord version, Instant createdAt) { }

    record Basis(String roundId, String graphVersion, Instant dataAsOf, Map<String, List<String>> issueCompanies,
            Reconstruction reconstruction) {
        public Basis(String roundId, String graphVersion, Instant dataAsOf, Map<String, List<String>> issueCompanies) {
            this(roundId, graphVersion, dataAsOf, issueCompanies, null);
        }
        public Basis {
            var copy = new LinkedHashMap<String, List<String>>();
            issueCompanies.forEach((issue, companies) -> copy.put(issue, List.copyOf(companies)));
            issueCompanies = Collections.unmodifiableMap(copy);
        }

        public List<String> keyIssueIds() { return List.copyOf(issueCompanies.keySet()); }
        public List<String> companyIds() { return issueCompanies.values().stream().flatMap(List::stream).distinct().toList(); }
    }
}
