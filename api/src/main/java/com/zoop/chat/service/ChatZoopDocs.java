package com.zoop.chat.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

import com.zoop.document.evidence.service.EvidenceService.Readability;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;

/**
 * ZOOP's approved documents as citable quotes ({@code Citation.sourceKind=zoop_doc}). Today these are the policies the team
 * approved and registered in {@code term_versions} (docs/legal): the terms of service ({@code policy.service}) and the privacy
 * policy ({@code policy.privacy}). Help and screen documents have no approved text yet, so nothing here serves them.
 *
 * <p>Each {@code ## } section of a version's body is one quote: its text and its code-point span {@code [start, end)} in that
 * body. Its id has the evidence id shape and is the SHA-256 of the document id, version, span and text, so the same section
 * of the same version always has the same id and an answer stays tied to the version it quoted.
 *
 * <p>A version is chosen at the run's asOf, or now without one: effective, not retired, and its term not retired. It is
 * read and cited only while it is also the version in effect now, so a version that was later replaced or whose term was
 * retired is never shown, not even in an answer stored while it was in effect; that answer is withheld, and its quote is
 * never swapped for the newer text. An approved body is never changed in place (docs/legal/README.md), so a version's
 * sections are read once and kept.
 */
@Component
public class ChatZoopDocs {
    /** The chat grant registry's source id for ZOOP's own approved documents. */
    public static final String SOURCE_ID = "zoop-docs";
    private static final String POLICY = "policy.";
    /** Every policy document {@code zoopPolicy.read} reads: {@code policy.} and the term id. */
    public static final List<String> POLICIES = List.of(POLICY + "service", POLICY + "privacy");

    /** One section of one document version. {@code title} is the document title and the section heading. */
    public record Quote(String evidenceId, String docId, String docVersion, String title, String text, int start, int end) { }

    /** A document version in effect: its id, version, title and sections in body order. */
    public record Document(String docId, String version, String title, List<Quote> quotes) {
        public Document {
            quotes = List.copyOf(quotes);
        }
    }

    private final NamedParameterJdbcTemplate jdbc;
    private final Clock clock;
    /** Sections by {@code termId\0version}; a registered body never changes. */
    private final Map<String, List<Quote>> sections = new ConcurrentHashMap<>();

    public ChatZoopDocs(NamedParameterJdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock;
    }

    /**
     * The version of {@code docId} in effect at {@code asOf} (now when null), or empty when none is or when it is no longer
     * the version in effect now (replaced, or its term retired, since {@code asOf}).
     */
    public Optional<Document> inEffect(String docId, Instant asOf) {
        if (docId == null || !docId.startsWith(POLICY)) return Optional.empty();
        String term = docId.substring(POLICY.length());
        Instant now = clock.instant();
        var then = versionAt(term, asOf != null ? asOf : now);
        if (then.isEmpty()) return Optional.empty();
        if (asOf != null && !versionAt(term, now).map(v -> v[0].equals(then.get()[0])).orElse(false)) {
            return Optional.empty();
        }
        String version = then.get()[0];
        String title = then.get()[1];
        return Optional.of(new Document(docId, version, title, sections(term, version, title)));
    }

    /** The version and title of {@code term} in effect at {@code at}. */
    private Optional<String[]> versionAt(String term, Instant at) {
        var rows = jdbc.query("""
                SELECT v.version, v.title_snapshot FROM term_versions v JOIN terms t ON t.id = v.term_id
                WHERE v.term_id = :term AND v.effective_at <= :at AND (v.retired_at IS NULL OR v.retired_at > :at)
                  AND (t.retired_at IS NULL OR t.retired_at > :at)
                """, new MapSqlParameterSource("term", term).addValue("at", Timestamp.from(at)),
                (rs, n) -> new String[] {rs.getString("version"), rs.getString("title_snapshot")});
        return rows.isEmpty() ? Optional.empty() : Optional.of(rows.getFirst());
    }

    /** The quote an id names in any registered version, or empty when it names none. */
    public Optional<Quote> byId(String evidenceId) {
        if (evidenceId == null || !evidenceId.startsWith("ev-")) return Optional.empty();
        var versions = jdbc.query("SELECT term_id, version, title_snapshot FROM term_versions ORDER BY term_id, version",
                new MapSqlParameterSource(),
                (rs, n) -> new String[] {rs.getString("term_id"), rs.getString("version"), rs.getString("title_snapshot")});
        for (String[] v : versions) {
            for (Quote q : sections(v[0], v[1], v[2])) {
                if (q.evidenceId().equals(evidenceId)) return Optional.of(q);
            }
        }
        return Optional.empty();
    }

    /**
     * Whether a quote may be shown for {@code asOf} (now when null): its version is the one in effect then and is still the
     * one in effect now ({@link #inEffect}).
     */
    public Readability readability(Quote quote, Instant asOf) {
        try {
            return inEffect(quote.docId(), asOf).filter(d -> d.version().equals(quote.docVersion())).isPresent()
                    ? Readability.READABLE : Readability.DENIED;
        } catch (DataAccessException | TransactionException unavailable) {
            return Readability.UNAVAILABLE;
        }
    }

    /**
     * {@link #readability} for an id: empty when it names no ZOOP document quote, {@code UNAVAILABLE} when the registry
     * cannot be read.
     */
    public Optional<Readability> check(String evidenceId, Instant asOf) {
        Optional<Quote> quote;
        try {
            quote = byId(evidenceId);
        } catch (DataAccessException | TransactionException unavailable) {
            return Optional.of(Readability.UNAVAILABLE);
        }
        return quote.map(q -> readability(q, asOf));
    }

    private List<Quote> sections(String term, String version, String title) {
        return sections.computeIfAbsent(term + "\u0000" + version, key -> split(POLICY + term, version, title,
                jdbc.queryForObject("SELECT body FROM term_versions WHERE term_id = :term AND version = :version",
                        new MapSqlParameterSource("term", term).addValue("version", version), String.class)));
    }

    /**
     * The {@code ## } sections of a body: each runs from its heading line to the next heading or the end, trailing white space
     * left out. Text before the first heading (the title and version lines) is not a quote.
     */
    static List<Quote> split(String docId, String version, String title, String body) {
        List<Integer> heads = new ArrayList<>();
        for (int i = 0; i < body.length(); ) {
            if (body.startsWith("## ", i)) heads.add(i);
            int next = body.indexOf('\n', i);
            if (next < 0) break;
            i = next + 1;
        }
        List<Quote> quotes = new ArrayList<>();
        for (int h = 0; h < heads.size(); h++) {
            int from = heads.get(h);
            int to = h + 1 < heads.size() ? heads.get(h + 1) : body.length();
            String text = body.substring(from, to).stripTrailing();
            int lineEnd = text.indexOf('\n');
            String heading = (lineEnd < 0 ? text : text.substring(0, lineEnd)).substring(3).strip();
            int start = body.codePointCount(0, from);
            int end = start + text.codePointCount(0, text.length());
            quotes.add(new Quote(id(docId, version, start, end, text), docId, version, title + " · " + heading, text,
                    start, end));
        }
        return List.copyOf(quotes);
    }

    static String id(String docId, String version, int start, int end, String text) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(("zoop_doc\n" + docId + "\n" + version + "\n"
                    + start + "\n" + end + "\n" + text).getBytes(StandardCharsets.UTF_8));
            return "ev-" + HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
