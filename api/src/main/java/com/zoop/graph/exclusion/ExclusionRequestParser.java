package com.zoop.graph.exclusion;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.graph.exclusion.ExclusionRequest.Exclude;
import com.zoop.graph.exclusion.ExclusionRequest.Handoff;
import com.zoop.graph.exclusion.ExclusionRequest.Lift;
import com.zoop.graph.exclusion.ExclusionRequest.Query;
import com.zoop.graph.exclusion.ExclusionRequest.Report;
import com.zoop.graph.exclusion.ExclusionRequest.Target;
import tools.jackson.databind.JsonNode;

/**
 * Reads the request file ({@code zoop-disclosure-exclusion-1}, closed). An {@code exclude} embeds the exposure report exactly as
 * {@code zoop-ai-handoff-exposure} printed it; the report is checked against the closed {@code ExposureReport} schema of
 * {@code docs/api/internal-ai-openapi.yaml} ({@code zoop-handoff-exposure-1}), so a report of another version or a hand-edited one
 * with an unknown key, a value of the wrong type, a reason or text outside its enum or const, or a list over its cap is refused
 * whole. Nothing is read from the AI side here: the report is the operator's input. An {@code exclude-query} names the change and
 * the versions instead, and the command reads the report from the AI service ({@link #report(JsonNode)} checks it the same way).
 * {@code requestId} names the command (a re-run of the same request returns the recorded result); a {@code lift} also names the
 * {@code expectedRevision} it was decided on and may ask for {@code laterVersions} (optional boolean, default false).
 */
public final class ExclusionRequestParser {
    public static final String SCHEMA_VERSION = "zoop-disclosure-exclusion-1";
    static final String REPORT_SCHEMA = "zoop-handoff-exposure-1";
    /** The producer caps a report at 6 MiB; the request adds a few fields around it. */
    public static final int MAX_BYTES = 7 * 1024 * 1024;

    /** A producer id, a handoff id included (the exposure contract's {@code handoffIds} pattern). */
    static final Pattern ID = Pattern.compile("[A-Za-z0-9._:-]{1,200}");
    private static final Pattern DIGEST = Pattern.compile("[a-f0-9]{64}");
    private static final Pattern EVIDENCE = Pattern.compile("ev-[a-f0-9]{64}");
    private static final Pattern ARTICLE = Pattern.compile("doc-[a-f0-9]{64}");
    private static final Pattern OPERATOR = Pattern.compile("[A-Za-z0-9._@-]{1,100}");
    private static final Pattern RELATION_CANDIDATE = Pattern.compile("rc-[a-f0-9]{64}");
    private static final int MAX_LIFT_TARGETS = 20_000;
    /** One exposure query selects at most 20 handoffs, one per version. */
    static final int MAX_QUERY_VERSIONS = 20;
    static final String CONSISTENCY = "shared locks on every opened ledger were held from the first read until this output";
    static final String EFFECT = "none: identity-only proposal for the selected handoffs; nothing was excluded, revised, overlaid, "
            + "activated or written, and an empty or smaller result never clears or narrows any existing exclusion";
    private static final Set<String> ISSUE_REASONS = Set.of("disposition-input", "involvement-lost", "source-document");
    private static final Set<String> RELATION_REASONS = Set.of("anchor", "anchor-undetermined", "basis-evidence", "evidence", "issue",
            "source-relation", "upstream-input");

    public ExclusionRequest parse(byte[] bytes) {
        Obj root;
        try {
            root = StrictJson.parseObject(bytes);
            String action = root.string("action");
            if (!SCHEMA_VERSION.equals(root.string("schemaVersion"))) throw new StrictJson.Malformed();
            String requestId = id(root.string("requestId"));
            String operator = operator(root.string("operator"));
            String reason = reason(root.string("reason"));
            if ("lift".equals(action)) {
                root.keys(Set.of("schemaVersion", "requestId", "action", "operator", "reason", "graphVersionId",
                        "expectedRevision", "targets"), Set.of("laterVersions"));
                List<Target> targets = new ArrayList<>();
                for (Obj target : root.objects("targets")) {
                    targets.add(target(target));
                }
                if (targets.isEmpty() || targets.size() > MAX_LIFT_TARGETS || new LinkedHashSet<>(targets).size() != targets.size()) {
                    throw new StrictJson.Malformed();
                }
                boolean laterVersions = root.has("laterVersions") && root.bool("laterVersions");
                return new Lift(requestId, Canonical.digest(root.node()), operator, reason, id(root.string("graphVersionId")),
                        root.count("expectedRevision"), targets, laterVersions);
            }
            if ("exclude-query".equals(action)) {
                root.exactly(Set.of("schemaVersion", "requestId", "action", "operator", "reason", "changed", "graphVersionIds"));
                Obj changed = root.object("changed");
                String cause = "s3-relation".equals(changed.string("kind")) ? "relation-retraction" : "source-change";
                changed(changed, cause);
                List<String> versions = new ArrayList<>();
                for (String versionId : root.strings("graphVersionIds")) {
                    versions.add(id(versionId));
                }
                if (versions.size() > MAX_QUERY_VERSIONS || new LinkedHashSet<>(versions).size() != versions.size()) {
                    throw new StrictJson.Malformed();
                }
                return new Query(requestId, Canonical.digest(root.node()), operator, reason, changed.node(), cause, versions);
            }
            if (!"exclude".equals(action)) throw new StrictJson.Malformed();
            root.exactly(Set.of("schemaVersion", "requestId", "action", "operator", "reason", "report"));
        } catch (StrictJson.Malformed | IllegalArgumentException invalid) {
            throw new ExclusionException(ExclusionFailure.REQUEST_INVALID);
        }
        try {
            return new Exclude(root.string("requestId"), Canonical.digest(root.node()), root.string("operator"),
                    reason(root.string("reason")), report(root.object("report")));
        } catch (StrictJson.Malformed | IllegalArgumentException invalid) {
            throw new ExclusionException(ExclusionFailure.REPORT_INVALID);
        }
    }

    /** An exposure report read from the AI service, checked exactly as an embedded one; {@code report_invalid} otherwise. */
    static Report report(JsonNode report) {
        try {
            return report(StrictJson.Obj.of(report));
        } catch (StrictJson.Malformed | IllegalArgumentException invalid) {
            throw new ExclusionException(ExclusionFailure.REPORT_INVALID);
        }
    }

    private static Report report(Obj report) {
        report.exactly(Set.of("schemaVersion", "changed", "cause", "identity", "scope", "basis", "consistency", "effect",
                "handoffs", "usage"));
        if (!REPORT_SCHEMA.equals(report.string("schemaVersion"))) throw new StrictJson.Malformed();
        String cause = report.string("cause");
        if (!Set.of("source-change", "relation-retraction").contains(cause)) throw new StrictJson.Malformed();
        changed(report.object("changed"), cause);
        Obj identity = report.object("identity").exactly(Set.of("boundInSelection", "recordedInIngestion"));
        identity.bool("boundInSelection");
        if (!identity.isNull("recordedInIngestion")) identity.bool("recordedInIngestion");
        Obj scope = report.object("scope").exactly(Set.of("selection", "handoffIds", "notCovered"));
        if (!"explicit".equals(scope.string("selection"))) throw new StrictJson.Malformed();
        scope.strings("notCovered");
        report.string("basis");
        if (!CONSISTENCY.equals(report.string("consistency")) || !EFFECT.equals(report.string("effect"))) {
            throw new StrictJson.Malformed();
        }
        Obj usage = report.object("usage").exactly(Set.of("providerCalls", "modelCalls"));
        if (usage.count("providerCalls") != 0 || usage.count("modelCalls") != 0) throw new StrictJson.Malformed();

        List<Handoff> handoffs = new ArrayList<>();
        Set<String> ids = new LinkedHashSet<>();
        for (Obj handoff : report.objects("handoffs")) {
            Handoff parsed = handoff(handoff, cause);
            if (!ids.add(parsed.handoffId())) throw new StrictJson.Malformed();
            handoffs.add(parsed);
        }
        // The selection the report names is exactly the handoffs it reports on (1 to 20), in its order.
        if (handoffs.isEmpty() || handoffs.size() > 20 || !List.copyOf(ids).equals(scope.strings("handoffIds"))) {
            throw new StrictJson.Malformed();
        }
        return new Report(cause, Canonical.digest(report.node()), handoffs);
    }

    private static void changed(Obj changed, String cause) {
        String kind = changed.string("kind");
        switch (kind) {
            case "document" -> {
                changed.exactly(Set.of("kind", "documentId", "documentVersion", "rawVersion"));
                text(changed.string("documentId"));
                digestOrNull(changed, "documentVersion");
                digestOrNull(changed, "rawVersion");
            }
            case "source" -> text(changed.exactly(Set.of("kind", "sourceId")).string("sourceId"));
            case "grant" -> {
                changed.exactly(Set.of("kind", "grantId", "revision"));
                text(changed.string("grantId"));
                if (!changed.isNull("revision")) text(changed.string("revision"));
            }
            case "s3-relation" -> {
                changed.exactly(Set.of("kind", "jobId", "relationCandidateId"));
                id(changed.string("jobId"));
                match(RELATION_CANDIDATE, changed.string("relationCandidateId"));
            }
            default -> throw new StrictJson.Malformed();
        }
        // A relation retraction is exactly an s3-relation change; every source change is one of the other three.
        if ("s3-relation".equals(kind) != "relation-retraction".equals(cause)) throw new StrictJson.Malformed();
    }

    private static Handoff handoff(Obj handoff, String cause) {
        handoff.exactly(Set.of("handoffId", "bundleSchema", "manifestDigest", "bundleDigest", "contentDigest", "bound", "exposed",
                "articles", "issues", "relations", "evidenceIds", "counts"));
        if (!"zoop-graph-handoff-bundle-7".equals(handoff.string("bundleSchema"))) throw new StrictJson.Malformed();
        if (handoff.array("articles").size() > 1000 || handoff.array("issues").size() > 2000
                || handoff.array("relations").size() > 10_000 || handoff.array("evidenceIds").size() > 20_000) {
            throw new StrictJson.Malformed();
        }
        List<Target> targets = new ArrayList<>();
        for (Obj article : handoff.objects("articles")) {
            article.exactly(Set.of("articleId", "articleVersion", "documentId", "documentVersion"));
            text(article.string("documentId"));
            match(DIGEST, article.string("documentVersion"));
            targets.add(new Target("article", match(ARTICLE, article.string("articleId")),
                    match(DIGEST, article.string("articleVersion"))));
        }
        for (Obj issue : handoff.objects("issues")) {
            issue.exactly(Set.of("id", "reasons"));
            reasons(issue, ISSUE_REASONS);
            targets.add(new Target("issue", id(issue.string("id")), ""));
        }
        for (Obj relation : handoff.objects("relations")) {
            relation.exactly(Set.of("id", "type", "reasons"));
            if (!Set.of("INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS").contains(relation.string("type"))) {
                throw new StrictJson.Malformed();
            }
            reasons(relation, RELATION_REASONS);
            targets.add(new Target("relation", id(relation.string("id")), ""));
        }
        for (String evidenceId : handoff.strings("evidenceIds")) {
            targets.add(new Target("evidence", match(EVIDENCE, evidenceId), ""));
        }
        Obj counts = handoff.object("counts").exactly(Set.of("articles", "issues", "relations", "evidence"));
        boolean exposed = handoff.bool("exposed");
        boolean bound = handoff.bool("bound");
        int articles = handoff.objects("articles").size();
        int evidence = handoff.strings("evidenceIds").size();
        if (counts.count("articles") != articles || counts.count("issues") != handoff.objects("issues").size()
                || counts.count("relations") != handoff.objects("relations").size() || counts.count("evidence") != evidence
                || new LinkedHashSet<>(targets).size() != targets.size()
                || exposed != !targets.isEmpty() || (exposed && !bound)
                // A relation retraction never withdraws article text or quotes (consumption rule 5).
                || ("relation-retraction".equals(cause) && (articles != 0 || evidence != 0))) {
            throw new StrictJson.Malformed();
        }
        return new Handoff(id(handoff.string("handoffId")), match(DIGEST, handoff.string("manifestDigest")),
                match(DIGEST, handoff.string("bundleDigest")), match(DIGEST, handoff.string("contentDigest")), exposed, targets);
    }

    private static Target target(Obj target) {
        String kind = target.string("kind");
        if ("article".equals(kind)) {
            target.exactly(Set.of("kind", "id", "articleVersion"));
            return new Target(kind, match(ARTICLE, target.string("id")), match(DIGEST, target.string("articleVersion")));
        }
        target.exactly(Set.of("kind", "id"));
        String id = "evidence".equals(kind) ? match(EVIDENCE, target.string("id")) : id(target.string("id"));
        return new Target(kind, id, "");
    }

    /** At least one reason, each from the schema's enum. */
    private static void reasons(Obj target, Set<String> allowed) {
        List<String> reasons = target.strings("reasons");
        if (reasons.isEmpty() || !allowed.containsAll(reasons)) throw new StrictJson.Malformed();
    }

    /** A producer id of 1 to 200 characters ({@code minLength}/{@code maxLength} count code points, as JSON Schema does). */
    private static void text(String value) {
        int length = value.codePointCount(0, value.length());
        if (length < 1 || length > 200) throw new StrictJson.Malformed();
    }

    private static void digestOrNull(Obj object, String name) {
        if (!object.isNull(name)) match(DIGEST, object.string(name));
    }

    private static String operator(String value) {
        return match(OPERATOR, value);
    }

    private static String reason(String value) {
        String reason = value.strip();
        if (reason.isEmpty() || reason.codePointCount(0, reason.length()) > 500) throw new StrictJson.Malformed();
        return reason;
    }

    private static String id(String value) {
        return match(ID, value);
    }

    private static String match(Pattern pattern, String value) {
        if (!pattern.matcher(value).matches()) throw new StrictJson.Malformed();
        return value;
    }
}
