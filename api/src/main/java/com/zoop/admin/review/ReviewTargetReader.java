package com.zoop.admin.review;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Pattern;

import com.zoop.ai.relation.RelationReviewRequest;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Malformed;
import com.zoop.common.json.StrictJson.Obj;

/**
 * Reads one S3 relation job result and the S2 extraction result it was built over into the administrator's review targets (a
 * filter projection, never the authority: ERD v6 section 26). Pure: JSON text goes in, rows come out.
 *
 * <p>One candidate row is one S2 event candidate (an event mention of one document) with the S3 relations that have it as an
 * event endpoint (user decision 2026-10-26). A relation with no event endpoint (company to company, or to a topic) is a
 * candidate of its own. A relation whose event endpoint names no S2 event candidate of this job is also a candidate of its own,
 * counted in {@link Projection#unknownEvents()} so the caller can log it. An S2 candidate the AI held on its identity comparison
 * ({@code disposition.status=held}) or rejected is left out together with its relations: the AI operator settles those, not the
 * administrator. A relation that has no verdict yet ({@code pending}) is left out until it has one.
 */
final class ReviewTargetReader {
    static final Pattern EVENT_CANDIDATE_ID = Pattern.compile("evc-[a-f0-9]{64}");
    private static final Pattern SOURCE_REVISION = Pattern.compile("0|[1-9][0-9]{0,8}");
    private static final Pattern REF = Pattern.compile("[\\x21-\\x7E]{1,200}");
    private static final Pattern TYPE = Pattern.compile("[A-Z][A-Z_]{0,63}");
    private static final Map<String, String> STATUS = Map.of("eligible", "ALLOW", "hold", "HOLD", "reject", "REJECT");

    private ReviewTargetReader() {
    }

    /** One review target as the sync writes it; {@code sourceJobId} and {@code sourceVersion} are the S3 job's. */
    record Row(String type, String externalId, String candidateId, String status, List<String> companyIds,
            List<String> relationTypes, String sourceRevision) {
    }

    record Projection(List<Row> rows, int unknownEvents) {
    }

    private record Event(boolean listed, Set<String> companies) {
    }

    private record Relation(String id, String type, String status, String revision, Set<String> companies,
            List<String> events) {
    }

    /**
     * @param s2Json the S2 {@code ExtractionJobContent} the S3 job's upstream names
     * @param s3Json the S3 {@code RelationJobContent}
     * @throws Malformed when either document is not the shape this reader needs
     */
    static Projection read(String s2Json, String s3Json) {
        Map<String, Event> events = events(StrictJson.parseObject(s2Json));
        Map<String, List<Relation>> grouped = new LinkedHashMap<>();
        List<Relation> alone = new ArrayList<>();
        int unknown = 0;
        for (Obj item : StrictJson.parseObject(s3Json).objects("relations")) {
            Relation relation = relation(item);
            if (relation.status() == null) continue;
            String owner = null;
            boolean known = false;
            for (String event : relation.events()) {
                Event found = events.get(event);
                if (found == null) continue;
                known = true;
                if (found.listed()) {
                    owner = event;
                    break;
                }
            }
            if (owner != null) grouped.computeIfAbsent(owner, key -> new ArrayList<>()).add(relation);
            else if (!known) {
                if (!relation.events().isEmpty()) unknown++;
                alone.add(relation);
            }
        }
        List<Row> rows = new ArrayList<>();
        grouped.forEach((event, relations) -> candidate(rows, event, events.get(event).companies(), relations));
        for (Relation relation : alone) candidate(rows, relation.id(), Set.of(), List.of(relation));
        return new Projection(rows, unknown);
    }

    private static Map<String, Event> events(Obj s2) {
        Map<String, Event> events = new LinkedHashMap<>();
        for (Obj item : s2.objects("eventCandidates")) {
            String id = matching(item.string("eventCandidateId"), EVENT_CANDIDATE_ID);
            boolean listed = "candidate".equals(item.string("state"))
                    && !"held".equals(item.object("disposition").string("status"));
            Set<String> companies = new TreeSet<>();
            for (Obj participant : item.object("mention").objects("participants")) {
                if (participant.has("companyId") && !participant.isNull("companyId")) {
                    companies.add(matching(participant.string("companyId"), REF));
                }
            }
            if (events.put(id, new Event(listed, companies)) != null) throw new Malformed();
        }
        return events;
    }

    private static Relation relation(Obj item) {
        String id = matching(item.string("relationCandidateId"), RelationReviewRequest.CANDIDATE_ID);
        String eligibility = item.object("eligibility").string("status");
        if (!eligibility.equals("pending") && !STATUS.containsKey(eligibility)) throw new Malformed();
        Set<String> companies = new TreeSet<>();
        List<String> events = new ArrayList<>();
        for (String role : List.of("subject", "object")) {
            Obj endpoint = item.object(role);
            String ref = matching(endpoint.string("ref"), REF);
            switch (endpoint.string("kind")) {
                case "company" -> companies.add(ref);
                case "event" -> events.add(ref);
                case "topic" -> { }
                default -> throw new Malformed();
            }
        }
        return new Relation(id, matching(item.string("type"), TYPE), STATUS.get(eligibility),
                matching(item.string("sourceRevision"), SOURCE_REVISION), companies, events);
    }

    /**
     * The candidate row and one relation row per relation. The candidate is HOLD while any relation is, else ALLOW while any is,
     * else REJECT. Its source revision is the sum of its relations' revisions: each only grows, so the sum grows whenever one
     * of them changes, which is all the sync needs to tell a newer reading from an older one.
     */
    private static void candidate(List<Row> rows, String candidateId, Set<String> participants, List<Relation> relations) {
        Set<String> companies = new TreeSet<>(participants);
        Set<String> types = new TreeSet<>();
        long revision = 0;
        for (Relation relation : relations) {
            companies.addAll(relation.companies());
            types.add(relation.type());
            revision += Long.parseLong(relation.revision());
        }
        String status = relations.stream().anyMatch(r -> r.status().equals("HOLD")) ? "HOLD"
                : relations.stream().anyMatch(r -> r.status().equals("ALLOW")) ? "ALLOW" : "REJECT";
        rows.add(new Row("candidate", candidateId, candidateId, status, List.copyOf(companies), List.copyOf(types),
                Long.toString(revision)));
        for (Relation relation : relations) {
            rows.add(new Row("relation", relation.id(), candidateId, relation.status(),
                    List.copyOf(relation.companies()), List.of(relation.type()), relation.revision()));
        }
    }

    private static String matching(String value, Pattern pattern) {
        if (!pattern.matcher(value).matches()) throw new Malformed();
        return value;
    }
}
