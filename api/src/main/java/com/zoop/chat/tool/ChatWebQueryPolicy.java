package com.zoop.chat.tool;

import java.text.Normalizer;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * What may leave ZOOP as a web search query (web search design 5): a short public phrase, such as a company name, a public
 * keyword or a period. The question, the conversation and anything about the member (holdings, quantities, prices paid,
 * returns, accounts, contact details) never do. The server builds queries from public names and keywords; this is the last
 * check before the provider, and it refuses rather than edits a query that fails it.
 */
public final class ChatWebQueryPolicy {
    /** The longest query, in code points. */
    public static final int MAX_LENGTH = 80;

    private static final Pattern EMAIL = Pattern.compile("[^\\s@]+@[^\\s@]+");
    private static final Pattern LINK = Pattern.compile("(?i)(https?:|www\\.|\\.(com|net|org|kr|io)\\b)");
    /** A run of digits and separators; six digits or more in one is an account, phone, resident or card number. */
    private static final Pattern NUMBER = Pattern.compile("\\d[\\d\\s.-]*\\d");
    /** A date or month (2026-10-29, 2026.10) is a public period, whatever its digit count. */
    private static final Pattern DATE = Pattern.compile("\\d{4}[-.]\\d{1,2}([-.]\\d{1,2})?");
    private static final Pattern CONTROL = Pattern.compile("\\p{Cntrl}");
    /** Words that tie a query to the member rather than to a public subject. */
    private static final List<String> PERSONAL = List.of("내 종목", "내종목", "내 주식", "나의", "제가", "보유", "매입", "평단",
            "수익률", "손익", "계좌", "잔고", "수량", "주문", "비밀번호", "주민", "이메일", "전화", "연락처", "관심 종목", "관심종목");

    private ChatWebQueryPolicy() {
    }

    /** The query as it is sent (NFKC, single spaces), or empty when it may not be sent. */
    public static Optional<String> checked(String query) {
        if (query == null) return Optional.empty();
        String normalized = Normalizer.normalize(query, Normalizer.Form.NFKC).strip().replaceAll("\\s+", " ");
        int length = normalized.codePointCount(0, normalized.length());
        // Tabs and line breaks became spaces; any other control character is refused.
        if (length < 2 || length > MAX_LENGTH || CONTROL.matcher(normalized).find()) return Optional.empty();
        String lower = normalized.toLowerCase(Locale.ROOT);
        if (EMAIL.matcher(normalized).find() || LINK.matcher(normalized).find() || longNumber(normalized)
                || PERSONAL.stream().anyMatch(lower::contains)) {
            return Optional.empty();
        }
        return Optional.of(normalized);
    }

    private static boolean longNumber(String query) {
        var numbers = NUMBER.matcher(query);
        while (numbers.find()) {
            String run = numbers.group().strip();
            if (run.replaceAll("\\D", "").length() >= 6 && !DATE.matcher(run).matches()) return true;
        }
        return false;
    }
}
