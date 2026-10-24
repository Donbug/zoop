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
import com.zoop.graph.exclusion.ExclusionRequest.Report;
import com.zoop.graph.exclusion.ExclusionRequest.Target;

/**
 * Reads the request file ({@code zoop-disclosure-exclusion-1}, closed). An {@code exclude} embeds the exposure report exactly as
 * {@code zoop-ai-handoff-exposure} printed it; the report is checked against the closed {@code ExposureReport} schema of
 * {@code docs/api/internal-ai-openapi.yaml} ({@code zoop-handoff-exposure-1}), so a report of another version or a hand-edited one
 * with an unknown key is refused whole. Nothing is read from the AI side here: the report is the operator's input.
 */
public final class ExclusionRequestParser {
    public static final String SCHEMA_VERSION = "zoop-disclosure-exclusion-1";
    static final String REPORT_SCHEMA = "zoop-handoff-exposure-1";
    /** The producer caps a report at 6 MiB; the request adds a few fields around it. */
    public static final int MAX_BYTES = 7 * 1024 * 1024;

    private static final Pattern ID = Pattern.compile("[A-Za-z0-9._:-]{1,200}");
    private static final Pattern DIGEST = Pattern.compile("[a-f0-9]{64}");
    private static final Pattern EVIDENCE = Pattern.compile("ev-[a-f0-9]{64}");
    private static final Pattern ARTICLE = Pattern.compile("doc-[a-f0-9]{64}");
    private static final Pattern OPERATOR = Pattern.compile("[A-Za-z0-9._@-]{1,100}");
    private static final int MAX_LIFT_TARGETS = 20_000;

    public ExclusionRequest parse(byte[] bytes) {
        Obj root;
        try {
            root = StrictJson.parseObject(bytes);
            String action = root.string("action");
            if (!SCHEMA_VERSION.equals(root.string("schemaVersion"))) throw new StrictJson.Malformed();
            String operator = operator(root.string("operator"));
            String reason = reason(root.string("reason"));
            if ("lift".equals(action)) {
                root.exactly(Set.of("schemaVersion", "action", "operator", "reason", "graphVersionId", "targets"));
                List<Target> targets = new ArrayList<>();
                for (Obj target : root.objects("targets")) {
                    targets.add(target(target));
                }
                if (targets.isEmpty() || targets.size() > MAX_LIFT_TARGETS || new LinkedHashSet<>(targets).size() != targets.size()) {
                    throw new StrictJson.Malformed();
                }
                return new Lift(operator, reason, id(root.string("graphVersionId")), targets);
            }
            if (!"exclude".equals(action)) throw new StrictJson.Malformed();
            root.exactly(Set.of("schemaVersion", "action", "operator", "reason", "report"));
        } catch (StrictJson.Malformed | IllegalArgumentException invalid) {
            throw new ExclusionException(ExclusionFailure.REQUEST_INVALID);
        }
        try {
            return new Exclude(root.string("operator"), reason(root.string("reason")), report(root.object("report")));
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
        report.object("identity").exactly(Set.of("boundInSelection", "recordedInIngestion"));
        report.object("identity").bool("boundInSelection");
        Obj scope = report.object("scope").exactly(Set.of("selection", "handoffIds", "notCovered"));
        if (!"explicit".equals(scope.string("selection"))) throw new StrictJson.Malformed();
        scope.strings("notCovered");
        report.string("basis");
        report.string("consistency");
        report.string("effect");
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
            case "document" -> changed.exactly(Set.of("kind", "documentId", "documentVersion", "rawVersion"));
            case "source" -> changed.exactly(Set.of("kind", "sourceId"));
            case "grant" -> changed.exactly(Set.of("kind", "grantId", "revision"));
            case "s3-relation" -> changed.exactly(Set.of("kind", "jobId", "relationCandidateId"));
            default -> throw new StrictJson.Malformed();
        }
        // A relation retraction is exactly an s3-relation change; every source change is one of the other three.
        if ("s3-relation".equals(kind) != "relation-retraction".equals(cause)) throw new StrictJson.Malformed();
    }

    private static Handoff handoff(Obj handoff, String cause) {
        handoff.exactly(Set.of("handoffId", "bundleSchema", "manifestDigest", "bundleDigest", "contentDigest", "bound", "exposed",
                "articles", "issues", "relations", "evidenceIds", "counts"));
        if (!"zoop-graph-handoff-bundle-7".equals(handoff.string("bundleSchema"))) throw new StrictJson.Malformed();
        List<Target> targets = new ArrayList<>();
        for (Obj article : handoff.objects("articles")) {
            article.exactly(Set.of("articleId", "articleVersion", "documentId", "documentVersion"));
            targets.add(new Target("article", match(ARTICLE, article.string("articleId")),
                    match(DIGEST, article.string("articleVersion"))));
        }
        for (Obj issue : handoff.objects("issues")) {
            issue.exactly(Set.of("id", "reasons"));
            if (issue.strings("reasons").isEmpty()) throw new StrictJson.Malformed();
            targets.add(new Target("issue", id(issue.string("id")), ""));
        }
        for (Obj relation : handoff.objects("relations")) {
            relation.exactly(Set.of("id", "type", "reasons"));
            if (!Set.of("INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS").contains(relation.string("type"))
                    || relation.strings("reasons").isEmpty()) {
                throw new StrictJson.Malformed();
            }
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
