package com.zoop.admin.transcripts;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import java.util.regex.Matcher;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import org.springframework.stereotype.Component;

/** A-ADM-02b: conservative, deterministic redaction. Never mutates stored conversations. */
@Component
public class TranscriptMasker {
    public record Owner(String id, String email, String name) { }
    public record Masked(String text, Map<String, Integer> counts) { }
    private record Rule(String kind, String replacement, Pattern pattern) { }

    private static final List<Rule> RULES = List.of(
            new Rule("email", "[이메일]", Pattern.compile(
                    "(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+\\.[A-Za-z0-9.-]+")),
            new Rule("rrn", "[주민등록번호]", Pattern.compile("(?<!\\d)\\d{6}[ -]?[1-8]\\d{6}(?!\\d)")),
            new Rule("phone", "[전화번호]", Pattern.compile(
                    "(?<!\\d)(?:(?:\\+82[ .-]?|0082[ .-]?)(?:10|2|[3-6]\\d)|0(?:1[016789]|2|[3-6]\\d))[ .-]?\\d{3,4}[ .-]?\\d{4}(?!\\d)")),
            new Rule("card", "[카드번호]", Pattern.compile("(?<![A-Za-z0-9])\\d(?:[ -]?\\d){12,18}(?![A-Za-z0-9])")),
            new Rule("account", "[계좌번호]", Pattern.compile("(?<![A-Za-z0-9])\\d(?:[ -]?\\d){7,24}(?![A-Za-z0-9])")));
    private static final Pattern QUERY = Pattern.compile("([?&])([^=&#\\s]+)=([^&#\\s]+)");
    private static final Pattern TOKEN_KEY = Pattern.compile("(?i).*token.*|.*password.*|.*secret.*|.*authorization.*|api[-_]?key|.*signature.*|sig|.*credential.*");
    private static final String DEFAULT_OWNER_NAME = "회원";
    private static final Pattern DATE = Pattern.compile(
            "(?<!\\d)(?:19|20)\\d{2}([./-]?)(?:0[1-9]|1[0-2])\\1(?:0[1-9]|[12]\\d|3[01])(?!\\d)");

    public static final List<String> RULE_NAMES = List.of("URL 토큰", "이메일", "회원 식별자", "주민등록번호",
            "전화번호", "카드번호", "계좌번호", "이름");

    /** Purpose must not itself copy personal data into audit_logs. */
    public static boolean containsSensitive(String value) {
        return !redact(value, null, new LinkedHashMap<>()).equals(value);
    }

    public Masked mask(String input, Owner owner) {
        if (input == null || input.length() > 1_000_000) throw new IllegalArgumentException("Masking input unavailable");
        Map<String, Integer> counts = new LinkedHashMap<>();
        return new Masked(redact(input, owner, counts), Map.copyOf(counts));
    }

    private static String redact(String input, Owner owner, Map<String, Integer> counts) {
        String text = query(input, counts);
        // Full email first; otherwise a member id contained in an email could split the address.
        text = apply(RULES.getFirst(), text, counts);
        if (owner != null) text = literal(text, owner.id(), "[회원]", "userId", counts);
        // Split around valid date shapes, so numeric rules cannot consume any part of a protected date.
        // No sentinel tokens are inserted into user input (which could otherwise collide with a placeholder).
        var dates = DATE.matcher(text);
        var output = new StringBuilder();
        int offset = 0;
        while (dates.find()) {
            output.append(numbers(text.substring(offset, dates.start()), counts)).append(dates.group());
            offset = dates.end();
        }
        text = output.append(numbers(text.substring(offset), counts)).toString();
        if (owner != null) {
            // Non-standard stored email/name values are masked literally too.
            text = literal(text, owner.email(), "[이메일]", "email", counts);
            if (owner.name() != null && !DEFAULT_OWNER_NAME.equals(owner.name())
                    && owner.name().codePointCount(0, owner.name().length()) >= 2)
                text = literal(text, owner.name(), "[이름]", "name", counts);
        }
        return text;
    }

    private static String numbers(String input, Map<String, Integer> counts) {
        String text = input;
        for (int index = 1; index < RULES.size(); index++) text = apply(RULES.get(index), text, counts);
        return text;
    }

    private static String apply(Rule rule, String input, Map<String, Integer> counts) {
        var matcher = rule.pattern().matcher(input);
        var output = new StringBuilder();
        while (matcher.find()) {
            boolean amount = "account".equals(rule.kind()) && matcher.group().chars().allMatch(Character::isDigit)
                    && matcher.end() < input.length() && "원억만주%".indexOf(input.charAt(matcher.end())) >= 0;
            if (amount) matcher.appendReplacement(output, Matcher.quoteReplacement(matcher.group()));
            else {
                counts.merge(rule.kind(), 1, Integer::sum);
                matcher.appendReplacement(output, Matcher.quoteReplacement(rule.replacement()));
            }
        }
        return matcher.appendTail(output).toString();
    }

    private static String query(String input, Map<String, Integer> counts) {
        var matcher = QUERY.matcher(input);
        var output = new StringBuilder();
        while (matcher.find()) {
            boolean sensitive;
            try { sensitive = TOKEN_KEY.matcher(URLDecoder.decode(matcher.group(2), StandardCharsets.UTF_8)).matches(); }
            catch (IllegalArgumentException malformed) { sensitive = true; }
            if (sensitive) {
                counts.merge("token", 1, Integer::sum);
                matcher.appendReplacement(output, Matcher.quoteReplacement(matcher.group(1) + matcher.group(2) + "=[토큰]"));
            } else matcher.appendReplacement(output, Matcher.quoteReplacement(matcher.group()));
        }
        return matcher.appendTail(output).toString();
    }

    private static String literal(String text, String secret, String replacement, String kind, Map<String, Integer> counts) {
        if (secret == null || secret.isBlank()) return text;
        int count = 0, offset = 0;
        while ((offset = text.indexOf(secret, offset)) >= 0) { count++; offset += secret.length(); }
        if (count == 0) return text;
        counts.merge(kind, count, Integer::sum);
        return text.replace(secret, replacement);
    }
}
