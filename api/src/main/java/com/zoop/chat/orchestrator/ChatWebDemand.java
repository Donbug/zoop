package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.Citation;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolPath;
import com.zoop.chat.tool.ChatToolResult;
import java.text.Normalizer;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Whether a requirement's own words ask for a source outside ZOOP (web search design 1 and 2): ZOOP's documents alone do not
 * meet it, though the internal read still comes first. A fixed set of Korean expressions, read deterministically and never by
 * a model. Company names that are also search engines (구글, 네이버) do not count, and a request written against the web
 * ("웹 검색 말고") is no request for it.
 */
public final class ChatWebDemand {
    private static final Pattern WHITESPACE = Pattern.compile("\\s+");
    private static final Pattern EXTERNAL = Pattern.compile(
            "(외부(출처|자료|기사|보도|뉴스|소식|언론|매체)|외신|해외(언론|매체|보도|기사|뉴스)|언론(보도|기사)"
                    + "|웹(검색|에서)|인터넷(검색|에서))(?!.{0,6}(말고|없이|빼고|제외|않|마))");
    /** Public-fact fields whose absence is safe to decide without a model. */
    private static final Map<String, List<String>> REQUIRED_FIELDS = Map.ofEntries(
            Map.entry("매출", List.of("매출", "revenue")),
            Map.entry("영업이익", List.of("영업이익", "operatingprofit")),
            Map.entry("순이익", List.of("순이익", "당기순이익", "netincome")),
            Map.entry("계약금액", List.of("계약금액", "계약규모", "contractvalue")),
            Map.entry("점유율", List.of("점유율", "marketshare")),
            Map.entry("생산량", List.of("생산량", "productionvolume")),
            Map.entry("출하량", List.of("출하량", "shipmentvolume")),
            Map.entry("주가", List.of("주가", "stockprice", "shareprice")),
            Map.entry("가격", List.of("가격", "price")),
            Map.entry("일정", List.of("일정", "예정일", "schedule")));

    private ChatWebDemand() {
    }

    public static boolean asksExternalSource(String requirement) {
        return EXTERNAL.matcher(WHITESPACE.matcher(requirement).replaceAll("")).find();
    }

    /** Reads one internal evidence id at the run's pinned version. */
    @FunctionalInterface
    public interface EvidenceReader {
        Optional<Citation> read(String evidenceId);
    }

    /**
     * Deterministic coverage of an internal read. The web may fill a public-fact gap only when this says it is incomplete.
     * A period or requested field is checked against readable citations. If evidence ids exist but none can currently be
     * read, their contents are treated as unknown rather than as a web gap: a refused internal source must not be replaced
     * by an outside search.
     */
    public record Coverage(boolean thin, boolean targets, boolean period, boolean fields, boolean citation) {
        public boolean incomplete() {
            return thin || !targets || !period || !fields || !citation;
        }
    }

    public static Coverage coverage(String requirement, Instant askedAt, List<String> targets,
            List<ChatToolResult> reads, EvidenceReader evidence) {
        boolean thin = reads.isEmpty() || reads.stream()
                .anyMatch(r -> r.items().isEmpty() || Boolean.TRUE.equals(r.truncated()));
        Set<String> found = new LinkedHashSet<>();
        Set<String> evidenceIds = new LinkedHashSet<>();
        List<String> text = new ArrayList<>();
        for (ChatToolResult read : reads) {
            evidenceIds.addAll(read.evidenceIds());
            for (ChatToolItem item : read.items()) {
                found.add(item.id());
                found.addAll(item.companyIds());
                evidenceIds.addAll(item.evidenceIds());
                text.add(item.label());
            }
            for (ChatToolPath path : read.paths()) {
                found.add(path.fromId());
                found.add(path.toId());
                path.steps().forEach(step -> {
                    found.add(step.sourceId());
                    found.add(step.targetId());
                    evidenceIds.addAll(step.evidenceIds());
                });
            }
        }
        List<Citation> cited = new ArrayList<>();
        for (String id : evidenceIds) evidence.read(id).ifPresent(cited::add);
        cited.forEach(c -> {
            text.add(c.articleTitle());
            text.add(c.quote());
        });

        boolean targetCoverage = targets.isEmpty() || found.containsAll(targets);
        boolean citationCoverage = !evidenceIds.isEmpty();
        Optional<ChatPeriods.Period> asked = ChatPeriods.parse(requirement, askedAt);
        boolean periodCoverage = asked.isEmpty() || cited.isEmpty() && !evidenceIds.isEmpty()
                || cited.stream().map(Citation::publishedAt).filter(java.util.Objects::nonNull)
                        .map(at -> at.atZone(ChatPeriods.KST).toLocalDate())
                        .anyMatch(day -> within(day, asked.orElseThrow()));
        String question = normalized(requirement);
        String available = normalized(String.join(" ", text.stream().filter(java.util.Objects::nonNull).toList()));
        List<List<String>> requested = REQUIRED_FIELDS.entrySet().stream()
                .filter(e -> question.contains(normalized(e.getKey()))
                        || e.getValue().stream().map(ChatWebDemand::normalized).anyMatch(question::contains))
                .map(Map.Entry::getValue).toList();
        boolean fieldCoverage = requested.isEmpty() || cited.isEmpty() && !evidenceIds.isEmpty()
                || requested.stream().allMatch(aliases -> aliases.stream().map(ChatWebDemand::normalized)
                        .anyMatch(available::contains));
        return new Coverage(thin, targetCoverage, periodCoverage, fieldCoverage, citationCoverage);
    }

    private static boolean within(LocalDate day, ChatPeriods.Period period) {
        return !day.isBefore(period.start()) && !day.isAfter(period.end());
    }

    private static String normalized(String value) {
        if (value == null) return "";
        return Normalizer.normalize(value, Normalizer.Form.NFKC).toLowerCase(java.util.Locale.ROOT)
                .replaceAll("[^\\p{L}\\p{N}]", "");
    }
}
