package com.zoop.graph.importer;

import java.time.YearMonth;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.graph.importer.HandoffBundle.Article;
import com.zoop.graph.importer.HandoffBundle.Evidence;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * A Java port of the producer's pure issue-summary contract ({@code ai/pipeline/.../issue_summary_contracts.py}:
 * {@code summary_basis}, {@code deterministic_code}, {@code result_version}, {@code result_digest}, {@code check_summary}) that the
 * strict {@link HandoffBundleVerifier} runs on every {@code issues[].summary} of a {@code zoop-graph-handoff-bundle-7}. The app
 * recomputes the whole decision table from the bundle itself and trusts no producer claim:
 *
 * <ol>
 *   <li>a HOLD/REJECT operator field verdict anywhere on the issue leaves exactly {@code unavailable/temporal-review-pending}
 *       with {@code source: null}: no summary text can exist in the bundle for that issue, {@code available} included;</li>
 *   <li>more than {@link #MAX_QUOTES} input quotes leaves exactly {@code unavailable/input-too-large};</li>
 *   <li>otherwise {@code not-requested} (no job, {@code source: null}), a job-coded {@code unavailable}
 *       ({@code producer-invalid}, {@code verifier-hold}, {@code verifier-reject}; its {@code source} pins the job, input and
 *       result digests and the basis it was written for) or an {@code available} summary.</li>
 * </ol>
 *
 * <p>An {@code available} summary is closed: 1..5 claims {@code c1..cn} of 1..280 code points with at least one Hangul syllable
 * and 1..5 sorted evidence ids each, all inside the basis quotes (the union of the issue's {@code mentions[].evidenceIds}, never
 * geography-only or verdict-only evidence); {@code text} is the claims joined by a newline; {@code evidenceIds} is their sorted
 * union; {@code resultVersion}, the basis digest and the result digest are recomputed; the producer and verifier kinds pair with
 * the bundle's execution mode (a replay is an authored answer, never an independent model's).
 *
 * <p>The summary is receipt-only: it never reaches the public graph snapshot. Reading it for {@code getEvent} is the caller's
 * job and must apply the current-rights and asOf gate to EVERY basis quote, not only to the cited ones.
 */
final class HandoffIssueSummary {
    static final String POLICY = "zoop-issue-summary-policy-1";
    static final int MAX_QUOTES = 60;
    static final int MAX_CLAIMS = 5;
    static final int MAX_CLAIM_QUOTES = 5;
    static final int MAX_CLAIM_TEXT = 280;
    static final String LANGUAGE = "ko";
    static final String NOT_REQUESTED = "not-requested";
    static final String TEMPORAL_PENDING = "temporal-review-pending";
    static final String INPUT_TOO_LARGE = "input-too-large";
    private static final Set<String> DETERMINISTIC = Set.of(NOT_REQUESTED, TEMPORAL_PENDING, INPUT_TOO_LARGE);
    private static final Set<String> JOB_CODES = Set.of("producer-invalid", "verifier-hold", "verifier-reject");
    private static final Set<String> HELD = Set.of("HOLD", "REJECT");

    private static final Pattern ID = Pattern.compile("[A-Za-z0-9._:-]{1,200}");
    private static final Pattern HASH = Pattern.compile("[a-f0-9]{64}");
    private static final Set<String> SOURCE_KEYS = Set.of("jobId", "inputDigest", "resultDigest", "basisDigest");
    private static final Set<String> AVAILABLE_KEYS = Set.of("status", "text", "claims", "evidenceIds", "generatedAt",
            "resultVersion", "language", "source", "producer", "verifier");
    private static final Set<String> PRODUCER_KEYS = Set.of("kind", "model", "reasoningEffort", "promptVersion",
            "schemaDigest", "runtimeIdentity");
    private static final Set<String> VERIFIER_KEYS = Set.of("kind", "model", "adapterIdentity", "requestDigest");
    private static final Set<String> CLAIM_KEYS = Set.of("claimId", "text", "evidenceIds");

    private HandoffIssueSummary() {
    }

    /**
     * Checks {@code issue.summary} against the whole decision table, computed from the issue and the bundle's own evidence and
     * articles. {@code executionMode}/{@code recordingKind} are the bundle's provenance pair.
     */
    static void verify(Obj issue, Map<String, Evidence> evidence, Map<String, Article> articles, String executionMode,
            String recordingKind) {
        ObjectNode basis = basis(issue, evidence, articles);
        String basisDigest = Canonical.digest(basis);
        String expected = deterministicCode(issue, basis);
        Obj summary = issue.object("summary");
        String status = summary.string("status");
        need(status.equals("available") || status.equals("unavailable"));
        if (status.equals("unavailable")) {
            summary.exactly(Set.of("status", "code", "source"));
            String code = summary.string("code");
            if (DETERMINISTIC.contains(code)) {
                // Accepted only while its own condition holds and no earlier rule decided: a held issue carries no other value.
                need(summary.isNull("source") && code.equals(expected == null ? NOT_REQUESTED : expected));
                return;
            }
            need(expected == null && JOB_CODES.contains(code));
            Obj source = source(summary.object("source"), basisDigest);
            ObjectNode body = StrictJson.newObject();
            body.put("status", "unavailable");
            body.put("code", code);
            need(source.string("resultDigest").equals(resultDigest(source, basisDigest, body)));
            return;
        }
        need(expected == null);
        summary.exactly(AVAILABLE_KEYS);
        boolean live = executionMode.equals("live") && recordingKind.equals("provider");
        boolean replay = executionMode.equals("replay") && recordingKind.equals("authored-test");
        need(live || replay);
        String producerKind = live ? "provider" : "authored-replay";
        String verifierKind = live ? "independent-verifier" : "authored-replay";

        Set<String> allowed = new TreeSet<>(HandoffBundleVerifier::compareCodePoints);
        for (JsonNode quote : basis.get("quotes").values()) {
            allowed.add(quote.get("evidenceId").stringValue());
        }
        JsonNode claims = summary.array("claims");
        need(claims.size() >= 1 && claims.size() <= MAX_CLAIMS);
        TreeSet<String> union = new TreeSet<>(HandoffBundleVerifier::compareCodePoints);
        List<String> texts = new ArrayList<>();
        int index = 0;
        for (JsonNode node : claims.values()) {
            Obj claim = Obj.of(node).exactly(CLAIM_KEYS);
            index++;
            need(claim.string("claimId").equals("c" + index));
            String text = claim.string("text");
            int length = text.codePointCount(0, text.length());
            need(length >= 1 && length <= MAX_CLAIM_TEXT && text.indexOf('\n') < 0 && text.indexOf('\r') < 0 && hangul(text));
            List<String> ids = claim.strings("evidenceIds");
            need(ids.size() >= 1 && ids.size() <= MAX_CLAIM_QUOTES && HandoffBundleVerifier.sortedUnique(ids) && allowed.containsAll(ids));
            union.addAll(ids);
            texts.add(text);
        }
        need(summary.string("text").equals(String.join("\n", texts)));
        need(summary.strings("evidenceIds").equals(new ArrayList<>(union)));
        need(LANGUAGE.equals(summary.string("language")));
        need(generatedAt(summary.string("generatedAt")));
        ObjectNode versionPreimage = StrictJson.newObject();
        versionPreimage.put("basisDigest", basisDigest);
        versionPreimage.set("claims", claims);
        need(summary.string("resultVersion").equals("isr-" + Canonical.digest(versionPreimage)));

        Obj producer = summary.object("producer").exactly(PRODUCER_KEYS);
        need(producer.string("kind").equals(producerKind));
        identityModel(producer, live);
        if (live) {
            need(between(producer.string("reasoningEffort"), 1, 50));
        } else {
            need(producer.isNull("reasoningEffort"));
        }
        need(between(producer.string("promptVersion"), 1, 200));
        need(HASH.matcher(producer.string("schemaDigest")).matches() && HASH.matcher(producer.string("runtimeIdentity")).matches());
        Obj verifier = summary.object("verifier").exactly(VERIFIER_KEYS);
        need(verifier.string("kind").equals(verifierKind));
        identityModel(verifier, live);
        need(HASH.matcher(verifier.string("adapterIdentity")).matches() && HASH.matcher(verifier.string("requestDigest")).matches());

        Obj source = source(summary.object("source"), basisDigest);
        ObjectNode body = ((ObjectNode) summary.node()).deepCopy();
        body.remove("source");
        need(source.string("resultDigest").equals(resultDigest(source, basisDigest, body)));
    }

    /**
     * The exact model input of one issue: its title and the union of {@code mentions[].evidenceIds} (sorted by evidence id), each
     * pinned to its article version and quote hash. A quote is {@code background} only when EVERY mention citing it is a
     * background (past-context) mention. Geography-only and verdict-only evidence is never part of it.
     */
    static ObjectNode basis(Obj issue, Map<String, Evidence> evidence, Map<String, Article> articles) {
        TreeMap<String, Boolean> background = new TreeMap<>(HandoffBundleVerifier::compareCodePoints);
        for (Obj mention : issue.objects("mentions")) {
            boolean past = mention.bool("background");
            for (String id : mention.strings("evidenceIds")) {
                background.merge(id, past, (known, now) -> known && now);
            }
        }
        ArrayNode quotes = StrictJson.newArray();
        TreeMap<String, ObjectNode> used = new TreeMap<>(HandoffBundleVerifier::compareCodePoints);
        for (Map.Entry<String, Boolean> entry : background.entrySet()) {
            Evidence record = evidence.get(entry.getKey());
            need(record != null);
            String key = HandoffBundleVerifier.articleKey(record.articleId(), record.articleVersion());
            Article article = articles.get(key);
            need(article != null);
            ObjectNode pinned = StrictJson.newObject();
            pinned.put("articleId", record.articleId());
            pinned.put("articleVersion", record.articleVersion());
            pinned.put("documentId", article.documentId());
            pinned.put("documentVersion", article.documentVersion());
            pinned.put("textSha256", article.textSha256());
            used.put(key, pinned);
            ObjectNode quote = quotes.addObject();
            quote.put("evidenceId", entry.getKey());
            quote.put("articleId", record.articleId());
            quote.put("articleVersion", record.articleVersion());
            quote.put("start", record.start());
            quote.put("end", record.end());
            quote.put("quoteSha256", record.quoteSha256());
            quote.put("context", entry.getValue() ? "background" : "report");
        }
        ObjectNode basis = StrictJson.newObject();
        basis.put("policy", POLICY);
        basis.put("issueId", issue.string("id"));
        basis.put("title", issue.string("title"));
        basis.set("quotes", quotes);
        ArrayNode usedArticles = basis.putArray("articles");
        used.values().forEach(usedArticles::add);
        return basis;
    }

    /** The zero-call rule table, in order: a held/rejected time field first, then an oversized input; {@code null} means a job may exist. */
    static String deterministicCode(Obj issue, ObjectNode basis) {
        for (Obj verdict : issue.objects("fieldVerdicts")) {
            if (HELD.contains(verdict.string("decision"))) {
                return TEMPORAL_PENDING;
            }
        }
        return basis.get("quotes").size() > MAX_QUOTES ? INPUT_TOO_LARGE : null;
    }

    private static Obj source(Obj source, String basisDigest) {
        source.exactly(SOURCE_KEYS);
        need(ID.matcher(source.string("jobId")).matches());
        for (String name : List.of("inputDigest", "resultDigest", "basisDigest")) {
            need(HASH.matcher(source.string(name)).matches());
        }
        need(source.string("basisDigest").equals(basisDigest));          // the job was produced for exactly THIS basis
        return source;
    }

    /** The digest a decisions pin and the bundle {@code source} carry: the job identity and basis around the result body. */
    private static String resultDigest(Obj source, String basisDigest, ObjectNode body) {
        ObjectNode preimage = StrictJson.newObject();
        preimage.put("jobId", source.string("jobId"));
        preimage.put("inputDigest", source.string("inputDigest"));
        preimage.put("basisDigest", basisDigest);
        preimage.set("result", body);
        return Canonical.digest(preimage);
    }

    /** A live block names its model (1..200 code points); an authored replay names none. */
    private static void identityModel(Obj block, boolean live) {
        if (live) {
            need(between(block.string("model"), 1, 200));
        } else {
            need(block.isNull("model"));
        }
    }

    private static boolean between(String value, int minimum, int maximum) {
        int length = value.codePointCount(0, value.length());
        return length >= minimum && length <= maximum;
    }

    private static boolean hangul(String text) {
        return text.codePoints().anyMatch(point -> point >= 0xAC00 && point <= 0xD7A3);
    }

    private static final Pattern GENERATED_AT = Pattern.compile(
            "([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\\.[0-9]{1,9})?(?:Z|[+-]([0-9]{2}):([0-9]{2}))");

    /**
     * The one {@code issues[].summary.generatedAt} grammar, shared with the producer's {@code validate_generated_at} (shared vectors:
     * {@code graph-handoff/summary-time-vectors.json}); no library parser decides. A FULL match of ASCII
     * {@code YYYY-MM-DDTHH:MM:SS[.f{1,9}](Z|+HH:MM|-HH:MM)} with an uppercase {@code T} and {@code Z}, then: year 1..9999, a real Gregorian
     * calendar day, hour at most 23, minute and second at most 59 (no leap second), a numeric offset of at most 18:00 with minutes at
     * most 59 ({@code +00:00}, {@code -00:00} and {@code Z} all accepted; any number of fraction digits 1..9 with trailing zeros).
     * A space, a compact or basic form, a comma fraction, a week or ordinal date, full-width digits or an unstated offset is refused.
     */
    static boolean generatedAt(String value) {
        if (value == null) {
            return false;
        }
        Matcher found = GENERATED_AT.matcher(value);
        if (!found.matches()) {
            return false;
        }
        int year = Integer.parseInt(found.group(1));
        int month = Integer.parseInt(found.group(2));
        if (year < 1 || month < 1 || month > 12) {
            return false;
        }
        int day = Integer.parseInt(found.group(3));
        if (day < 1 || day > YearMonth.of(year, month).lengthOfMonth()) {
            return false;
        }
        if (Integer.parseInt(found.group(4)) > 23 || Integer.parseInt(found.group(5)) > 59 || Integer.parseInt(found.group(6)) > 59) {
            return false;
        }
        if (found.group(7) != null) {
            int offsetHour = Integer.parseInt(found.group(7));
            int offsetMinute = Integer.parseInt(found.group(8));
            return offsetMinute <= 59 && offsetHour <= 18 && (offsetHour < 18 || offsetMinute == 0);
        }
        return true;
    }

    private static void need(boolean condition) {
        if (!condition) {
            throw new StrictJson.Malformed();
        }
    }
}
