package com.zoop.feedback;

import java.util.regex.Pattern;

/** Read-time copy of the prototype masking policy; stored/member-visible reasons stay unchanged. */
final class FeedbackReasonMasker {
  private static final Pattern EMAIL =
      Pattern.compile("[A-Za-z0-9._%+\\-]+@[A-Za-z0-9\\-]+(?:\\.[A-Za-z0-9\\-]+)+");
  private static final Pattern RRN = Pattern.compile("(?<!\\d)\\d{6}[-\\s]?[1-8]\\d{6}(?!\\d)");
  private static final Pattern CARD =
      Pattern.compile(
          "(?<!\\d)(?:\\d{4}[-\\s]?){3}\\d{4}(?!\\d)|(?<!\\d)3[47]\\d{2}[-\\s]?\\d{6}[-\\s]?\\d{5}(?!\\d)");
  private static final Pattern MOBILE =
      Pattern.compile("(?<!\\d)(?:\\+82[-\\s]?)?0?1[016-9][-.\\s]?\\d{3,4}[-.\\s]?\\d{4}(?!\\d)");
  private static final Pattern LANDLINE =
      Pattern.compile(
          "(?<!\\d)(?:\\+82[-\\s]?)?0?(?:2|[3-6]\\d)[-.\\s]?\\d{3,4}[-.\\s]?\\d{4}(?!\\d)");
  private static final Pattern ACCOUNT =
      Pattern.compile("(?<!\\d)\\d{2,6}(?:-\\d{2,8}){1,3}(?!\\d)|(?<!\\d)\\d{10,14}(?!\\d)");
  private static final Pattern DATE = Pattern.compile("\\d{4}-\\d{1,2}-\\d{1,2}");

  private FeedbackReasonMasker() {}

  static String mask(String text, String ownerEmail, String ownerName) {
    if (text == null) return null;
    text = literal(text, ownerEmail, "[이메일]");
    if (ownerName != null && ownerName.strip().length() >= 2)
      text = literal(text, ownerName.strip(), "[이름]");
    text = EMAIL.matcher(text).replaceAll("[이메일]");
    text = RRN.matcher(text).replaceAll("[주민등록번호]");
    text = CARD.matcher(text).replaceAll("[카드번호]");
    text = MOBILE.matcher(text).replaceAll("[전화번호]");
    text = LANDLINE.matcher(text).replaceAll("[전화번호]");
    return ACCOUNT
        .matcher(text)
        .replaceAll(
            match -> {
              String value = match.group();
              long digits = value.chars().filter(Character::isDigit).count();
              return DATE.matcher(value).matches() || digits < 9 || digits > 16 ? value : "[계좌번호]";
            });
  }

  private static String literal(String text, String value, String replacement) {
    return value == null || value.isBlank()
        ? text
        : Pattern.compile(Pattern.quote(value), Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE)
            .matcher(text)
            .replaceAll(replacement);
  }
}
