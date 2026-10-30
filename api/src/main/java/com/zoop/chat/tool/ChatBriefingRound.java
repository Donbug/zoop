package com.zoop.chat.tool;

import java.time.LocalDate;
import java.util.regex.Pattern;

/**
 * Which published briefing round a {@code briefing.read} reads, as its first target: {@code briefing:latest} (the latest
 * published round), {@code briefing:<date>} (that KST day's latest round) or {@code briefing:<date>:<edition>}
 * ({@code morning} or {@code evening}). The server writes it from the requirement's own words; a model never does.
 */
public record ChatBriefingRound(LocalDate date, String edition) {
    /** The latest published round, whatever its day or edition. */
    public static final String LATEST = "briefing:latest";

    private static final Pattern REF = Pattern.compile("briefing:(\\d{4}-\\d{2}-\\d{2})(?::(morning|evening))?");
    private static final Pattern MORNING = Pattern.compile("아침|출근|오전|모닝");
    private static final Pattern EVENING = Pattern.compile("저녁|퇴근|오후|이브닝");

    public ChatBriefingRound {
        if (edition != null && date == null) throw new IllegalArgumentException("an edition needs its day");
        if (edition != null && !edition.equals("morning") && !edition.equals("evening")) {
            throw new IllegalArgumentException("edition is morning or evening");
        }
    }

    /** Whether {@code target} names a round; the other targets of a briefing read are company ids. */
    public static boolean isRef(String target) {
        return LATEST.equals(target) || REF.matcher(target).matches();
    }

    /** The round a target names; throws {@link IllegalArgumentException} for anything else. */
    public static ChatBriefingRound parse(String target) {
        if (LATEST.equals(target)) return new ChatBriefingRound(null, null);
        var m = REF.matcher(target);
        if (!m.matches()) throw new IllegalArgumentException("not a briefing round: " + target);
        return new ChatBriefingRound(LocalDate.parse(m.group(1)), m.group(2));
    }

    /**
     * The round a requirement's words name: the day it names (resolved by the caller from the question's own period, null
     * when none) and the edition its words name (아침·출근 → morning, 저녁·퇴근 → evening). A day without an edition reads
     * that day's latest round; an edition without a day reads today's.
     */
    public static String ref(String words, LocalDate namedDay, LocalDate today) {
        boolean morning = MORNING.matcher(words).find();
        boolean evening = EVENING.matcher(words).find();
        String edition = morning == evening ? null : morning ? "morning" : "evening";
        LocalDate day = namedDay != null ? namedDay : edition != null ? today : null;
        if (day == null) return LATEST;
        return "briefing:" + day + (edition == null ? "" : ":" + edition);
    }

    public String ref() {
        if (date == null) return LATEST;
        return "briefing:" + date + (edition == null ? "" : ":" + edition);
    }
}
