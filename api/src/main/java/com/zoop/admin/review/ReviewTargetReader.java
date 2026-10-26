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
import tools.jackson.databind.JsonNode;

/**
 * Reads one S3 relation job result and the S2 extraction result it was built over into the administrator's review targets (a
 * filter projection, never the authority: ERD v6 section 26). Pure: JSON text goes in, rows come out.
 *
 * <p>One candidate row is one S2 event candidate (an event mention of one document) with the S3 relations that have it as an
 * event endpoint (user decision 2026-10-26). A relation with no event endpoint (company to company, or to a topic) is a
 * candidate of its own. A relation whose event endpoint names no S2 event candidate of this job is also a candidate of its own,
 * counted in {@link Projection#unknownEvents()} so the caller can log it. An S2 candidate the AI held on its identity comparison
 * ({@code disposition.status=held}) or rejected is left out, and so is every relation that has it as ANY of its event endpoints
 * (an event-to-event relation included): the AI operator settles those, not the administrator. A relation that has no verdict
 * yet ({@code pending}) is left out until it has one.
 *
 * <p>Only the two documents' shape (the arrays) is all-or-nothing. One unreadable event candidate or relation is left out and
 * counted in {@link Projection#skipped()}, so it never hides the rest of the job. An unreadable event whose id is still readable
 * counts as not listed (its relations are left out with it); when an event's id itself is unreadable, a relation naming an
 * unknown event is left out too rather than standing alone, since it may belong to that event.
 */
final class ReviewTargetReader {
    static final Pattern EVENT_CANDIDATE_ID = Pattern.compile("evc-[a-f0-9]{64}");
    private static final Pattern SOURCE_REVISION = Pattern.compile("0|[1-9][0-9]{0,8}");
    /** A source id as the AI writes it (any language), without control characters or surrounding blanks. */
    private static final Pattern REF = Pattern.compile("[^\\p{Cntrl}\\s](?:[^\\p{Cntrl}]{0,198}[^\\p{Cntrl}\\s])?");
    private static final Pattern TYPE = Pattern.compile("[A-Z][A-Z0-9_]{0,63}");
    private static final Map<String, String> STATUS = Map.of("eligible", "ALLOW", "hold", "HOLD", "reject", "REJECT");

    private ReviewTargetReader() {
    }

    /** One review target as the sync writes it; {@code sourceJobId} and {@code sourceVersion} are the S3 job's. */
    record Row(String type, String externalId, String candidateId, String status, List<String> companyIds,
            List<String> relationTypes, String sourceRevision, Display display, Boolean operatorApproved) {
    }

    /**
     * What the candidate list shows without calling the AI service. {@code issueId}, {@code title}, {@code action} and
     * {@code eventTime} come from the S2 event candidate and are null for a relation row and for a candidate without an event.
     */
    record Display(String issueId, String title, String action, String target, String eventTime, int evidenceCount,
            List<Company> companies, List<String> reasons) {
    }

    /** A company as the source names it: {@code sourceId} is the AI source company id (not an app id), {@code role} may be null. */
    record Company(String sourceId, String name, String role) {
    }

    record Projection(List<Row> rows, int unknownEvents, int skipped) {
    }

    private record Event(boolean listed, Set<String> companies, String issueId, String title, String action, String target,
            String eventTime, int citations, List<Company> participants) {
        static final Event UNLISTED = new Event(false, Set.of(), null, null, null, null, null, 0, List.of());
    }

    private record Events(Map<String, Event> byId, int skipped, boolean unidentified) {
    }

    private record Relation(String id, String type, String status, String revision, Set<String> companies,
            List<String> events, int citations, List<String> reasons, boolean operatorApproved) {
    }

    /**
     * @param s2Json the S2 {@code ExtractionJobContent} the S3 job's upstream names
     * @param s3Json the S3 {@code RelationJobContent}
     * @throws Malformed when either document is not an object with its array ({@code eventCandidates}, {@code relations})
     */
    static Projection read(String s2Json, String s3Json) {
        Events events = events(StrictJson.parseObject(s2Json));
        JsonNode items = StrictJson.parseObject(s3Json).array("relations");
        Map<String, List<Relation>> grouped = new LinkedHashMap<>();
        List<Relation> alone = new ArrayList<>();
        int unknown = 0;
        int skipped = events.skipped();
        for (JsonNode item : items.values()) {
            Relation relation;
            try {
                relation = relation(Obj.of(item));
            } catch (Malformed unreadable) {
                skipped++;
                continue;
            }
            if (relation.status() == null) continue;
            String owner = null;
            boolean blocked = false;
            boolean missing = false;
            for (String event : relation.events()) {
                Event found = events.byId().get(event);
                if (found == null) missing = true;
                else if (!found.listed()) blocked = true;
                else if (owner == null) owner = event;
            }
            if (blocked) continue;
            if (missing) {
                unknown++;
                if (events.unidentified()) continue;
            }
            if (owner != null) grouped.computeIfAbsent(owner, key -> new ArrayList<>()).add(relation);
            else alone.add(relation);
        }
        List<Row> rows = new ArrayList<>();
        grouped.forEach((event, relations) -> candidate(rows, event, events.byId().get(event), relations));
        for (Relation relation : alone) candidate(rows, relation.id(), null, List.of(relation));
        return new Projection(rows, unknown, skipped);
    }

    private static Events events(Obj s2) {
        Map<String, Event> events = new LinkedHashMap<>();
        Set<String> duplicated = new TreeSet<>();
        int skipped = 0;
        boolean unidentified = false;
        for (JsonNode node : s2.array("eventCandidates").values()) {
            Obj item;
            String id;
            try {
                item = Obj.of(node);
                id = matching(item.string("eventCandidateId"), EVENT_CANDIDATE_ID);
            } catch (Malformed unreadable) {
                skipped++;
                unidentified = true;
                continue;
            }
            Event event;
            try {
                event = event(item);
            } catch (Malformed unreadable) {
                skipped++;
                event = Event.UNLISTED;
            }
            if (events.putIfAbsent(id, event) != null) duplicated.add(id);
        }
        // Two candidates under one id cannot be told apart: neither is listed, and their relations are left out.
        for (String id : duplicated) {
            events.put(id, Event.UNLISTED);
            skipped++;
        }
        return new Events(events, skipped, unidentified);
    }

    private static Event event(Obj item) {
        Obj disposition = item.object("disposition");
        boolean listed = "candidate".equals(item.string("state")) && !"held".equals(disposition.string("status"));
        Obj mention = item.object("mention");
        Set<String> companies = new TreeSet<>();
        List<Company> participants = new ArrayList<>();
        for (Obj participant : mention.objects("participants")) {
            String sourceId = participant.has("companyId") && !participant.isNull("companyId")
                    ? matching(participant.string("companyId"), REF) : null;
            if (sourceId != null) companies.add(sourceId);
            participants.add(new Company(sourceId, participant.string("name"), participant.string("role")));
        }
        String issueId = disposition.has("targetEventId") ? disposition.stringOrNull("targetEventId") : null;
        return new Event(listed, companies, issueId, mention.string("title"), mention.string("action"), mention.stringOrNull("target"),
                mention.stringOrNull("eventTime"), item.array("citations").size(), List.copyOf(participants));
    }

    private static Relation relation(Obj item) {
        String id = matching(item.string("relationCandidateId"), RelationReviewRequest.CANDIDATE_ID);
        Obj eligibility = item.object("eligibility");
        String status = eligibility.string("status");
        if (!status.equals("pending") && !STATUS.containsKey(status)) throw new Malformed();
        Set<String> reasons = new TreeSet<>();
        if (eligibility.has("reasons")) {
            for (Obj reason : eligibility.objects("reasons")) reasons.add(reason.string("code"));
        }
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
        int citations = item.array("citations").size();
        return new Relation(id, matching(item.string("type"), TYPE), STATUS.get(status),
                matching(item.string("sourceRevision"), SOURCE_REVISION), companies, events, citations, List.copyOf(reasons),
                operatorApproved(eligibility));
    }

    /** The AI eligibility rests on an operator's final approval ({@code approvalBasis.kind}), not an automatic verdict. */
    private static boolean operatorApproved(Obj eligibility) {
        if (!eligibility.has("approvalBasis") || eligibility.isNull("approvalBasis")) return false;
        return "operator-final-approval".equals(eligibility.object("approvalBasis").string("kind"));
    }

    /**
     * The candidate row and one relation row per relation. The candidate is HOLD while any relation is, else ALLOW while any is,
     * else REJECT. Its source revision is the sum of its relations' revisions: each only grows, so the sum grows whenever one
     * of them changes, which is all the sync needs to tell a newer reading from an older one. {@code event} is null for a
     * relation that is a candidate of its own.
     */
    private static void candidate(List<Row> rows, String candidateId, Event event, List<Relation> relations) {
        Set<String> companies = new TreeSet<>(event == null ? Set.of() : event.companies());
        Set<String> types = new TreeSet<>();
        Set<String> reasons = new TreeSet<>();
        long revision = 0;
        for (Relation relation : relations) {
            companies.addAll(relation.companies());
            types.add(relation.type());
            reasons.addAll(relation.reasons());
            revision += Long.parseLong(relation.revision());
        }
        String status = relations.stream().anyMatch(r -> r.status().equals("HOLD")) ? "HOLD"
                : relations.stream().anyMatch(r -> r.status().equals("ALLOW")) ? "ALLOW" : "REJECT";
        Display display = event == null
                ? new Display(null, null, null, null, null, relations.getFirst().citations(), named(List.of(), companies, true),
                        List.copyOf(reasons))
                : new Display(event.issueId(), event.title(), event.action(), event.target(), event.eventTime(), event.citations(),
                        named(event.participants(), companies, true), List.copyOf(reasons));
        rows.add(new Row("candidate", candidateId, candidateId, status, List.copyOf(companies), List.copyOf(types),
                Long.toString(revision), display, null));
        List<Company> participants = event == null ? List.of() : event.participants();
        for (Relation relation : relations) {
            rows.add(new Row("relation", relation.id(), candidateId, relation.status(),
                    List.copyOf(relation.companies()), List.of(relation.type()), relation.revision(),
                    new Display(null, null, null, null, null, relation.citations(),
                            named(participants, relation.companies(), false), relation.reasons()),
                    relation.operatorApproved()));
        }
    }

    /**
     * Companies with the S2 participant's name and role where it names the id; any other id stands in for its own name. With
     * {@code everyParticipant} the participants the S2 mention lists without a relation come first too.
     */
    private static List<Company> named(List<Company> participants, Set<String> ids, boolean everyParticipant) {
        List<Company> named = new ArrayList<>();
        Set<String> listed = new TreeSet<>();
        for (Company company : participants) {
            if (everyParticipant || (company.sourceId() != null && ids.contains(company.sourceId()))) {
                named.add(company);
                if (company.sourceId() != null) listed.add(company.sourceId());
            }
        }
        for (String id : ids) if (!listed.contains(id)) named.add(new Company(id, id, null));
        return List.copyOf(named);
    }

    private static String matching(String value, Pattern pattern) {
        if (!pattern.matcher(value).matches()) throw new Malformed();
        return value;
    }
}
