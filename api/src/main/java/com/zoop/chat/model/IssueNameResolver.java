package com.zoop.chat.model;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

import com.zoop.chat.tool.ChatToolUnavailable;
import com.zoop.common.exception.CustomException;
import com.zoop.graph.read.GraphContextLookup;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;

/**
 * Resolves issues written in a question to the issue ids of the run's pinned public graph (decision of 2026-10-27), the way
 * {@link CompanyNameResolver} resolves companies: an issue is named when the question contains its whole title, or both its
 * target and its action ("HBM 공급 계약"), spacing and latin case aside. Issues named by the same words (the same title, or
 * the same target and action) are one {@link Mention} with several candidates, which the orchestrator asks about instead of
 * guessing. An issue whose title was written is not also named by its target and action. The router model never resolves
 * issues.
 */
public class IssueNameResolver {
    /** One visible issue; {@code label} tells issues with the same words apart by their event time. */
    public record Issue(String id, String label) { }

    /** The words found in the text and every issue they name. */
    public record Mention(String text, List<Issue> issues) {
        public boolean ambiguous() {
            return issues.size() > 1;
        }
    }

    /** The issues of one pinned graph, read once for every text of a run. */
    @FunctionalInterface
    public interface Names {
        List<Mention> mentions(String text);
    }

    record Entry(String id, String title, String target, String action, String eventTime) { }

    static final Names NONE = text -> List.of();
    private static final int MIN_WORDS = 2;

    private final PublicGraphReader graphs;

    public IssueNameResolver(PublicGraphReader graphs) {
        this.graphs = graphs;
    }

    /**
     * The issue names of the public graph a run pinned; none when it pinned no graph. A version, snapshot or database that
     * cannot be read is {@link ChatToolUnavailable}, as it would be for the run's reads.
     */
    public Names at(String graphVersion, Instant asOf) {
        if (graphVersion == null) return NONE;
        List<PublicGraphSnapshot.Issue> issues;
        try {
            issues = new GraphContextLookup(graphs.read(null, graphVersion, asOf).graph()).issues();
        } catch (CustomException | DataAccessException | TransactionException unavailable) {
            throw new ChatToolUnavailable("graph version " + graphVersion + " cannot be read", unavailable);
        }
        List<Entry> entries = issues.stream()
                .map(i -> new Entry(i.issueId(), i.label(), i.target(), i.action(), i.eventTime())).toList();
        return text -> match(text, entries);
    }

    /** Mentions in order of appearance. Pure: the issues are passed in. */
    static List<Mention> match(String text, List<Entry> issues) {
        String haystack = flat(text);
        record Hit(int at, String key, String words, Entry issue) { }
        List<Hit> titled = new ArrayList<>();
        List<Hit> paired = new ArrayList<>();
        for (Entry issue : issues) {
            String title = flat(issue.title());
            int at = enough(title) ? haystack.indexOf(title) : -1;
            if (at >= 0) {
                titled.add(new Hit(at, "title\0" + title, issue.title(), issue));
                continue;
            }
            String target = flat(issue.target());
            String action = flat(issue.action());
            if (!enough(target) || !enough(action)) continue;
            int t = haystack.indexOf(target);
            int a = haystack.indexOf(action);
            if (t >= 0 && a >= 0) {
                paired.add(new Hit(Math.min(t, a), pair(issue), issue.target() + " " + issue.action(), issue));
            }
        }
        // Words that name a titled issue's target and action mean that issue, not every other issue that shares them.
        Set<String> named = new HashSet<>();
        titled.forEach(h -> named.add(pair(h.issue())));
        paired.removeIf(h -> named.contains(h.key()));

        List<Hit> hits = new ArrayList<>(titled);
        hits.addAll(paired);
        hits.sort(Comparator.comparingInt(Hit::at).thenComparing(h -> h.issue().id()));
        Map<String, List<Hit>> byKey = new LinkedHashMap<>();
        hits.forEach(h -> byKey.computeIfAbsent(h.key(), k -> new ArrayList<>()).add(h));
        List<Mention> mentions = new ArrayList<>();
        for (List<Hit> group : byKey.values()) {
            boolean shared = group.size() > 1;
            mentions.add(new Mention(group.getFirst().words(), group.stream()
                    .map(h -> new Issue(h.issue().id(), shared ? label(h.issue()) : h.issue().title())).toList()));
        }
        return List.copyOf(mentions);
    }

    private static String pair(Entry issue) {
        return "pair\0" + flat(issue.target()) + "\0" + flat(issue.action());
    }

    /** How a clarification offers an issue that shares its words: the title with its event time. */
    private static String label(Entry issue) {
        return issue.eventTime() == null ? issue.title() : issue.title() + " (" + issue.eventTime() + ")";
    }

    private static String flat(String words) {
        return words == null ? "" : words.replaceAll("\\s+", "").toLowerCase(Locale.ROOT);
    }

    private static boolean enough(String words) {
        return words.codePointCount(0, words.length()) >= MIN_WORDS;
    }
}
