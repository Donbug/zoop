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

    public static final List<String> RULE_NAMES = List.of("URL 토큰", "이메일", "회원 식별자", "주민등록번호",
            "전화번호", "카드번호", "계좌번호", "이름");

    /** Purpose must not itself copy personal data into audit_logs. */
    public static boolean containsSensitive(String value) {
        return RULES.stream().anyMatch(rule -> rule.pattern().matcher(value).find())
                || !query(value, new LinkedHashMap<>()).equals(value);
    }

    public Masked mask(String input, Owner owner) {
        if (input == null || input.length() > 1_000_000) throw new IllegalArgumentException("Masking input unavailable");
        Map<String, Integer> counts = new LinkedHashMap<>();
        String text = query(input, counts);
        // Full email first; otherwise a member id contained in an email could split the address.
        for (int index = 0; index < RULES.size(); index++) {
            Rule rule = RULES.get(index);
            var matcher = rule.pattern().matcher(text);
            int count = 0;
            while (matcher.find()) count++;
            if (count > 0) {
                counts.merge(rule.kind(), count, Integer::sum);
                text = matcher.replaceAll(rule.replacement());
            }
            if (index == 0 && owner != null) text = literal(text, owner.id(), "[회원]", "userId", counts);
        }
        if (owner != null) {
            // Non-standard stored email/name values are masked literally too.
            text = literal(text, owner.email(), "[이메일]", "email", counts);
            text = literal(text, owner.name(), "[이름]", "name", counts);
        }
        return new Masked(text, Map.copyOf(counts));
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
