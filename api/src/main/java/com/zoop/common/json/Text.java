package com.zoop.common.json;

import java.nio.CharBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;

/** Text rules shared by the operator request, export and AI result validation. */
public final class Text {
    private Text() {
    }

    /** UTF-8 bytes, or {@code null} when the string has an unpaired surrogate (it has no UTF-8 form). */
    public static byte[] strictUtf8(String value) {
        try {
            var buffer = StandardCharsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).encode(CharBuffer.wrap(value));
            byte[] bytes = new byte[buffer.remaining()];
            buffer.get(bytes);
            return bytes;
        } catch (CharacterCodingException error) {
            return null;
        }
    }

    public static int codePoints(String value) {
        return value.codePointCount(0, value.length());
    }

    /** Well-formed UTF-16 without U+0000, which PostgreSQL text cannot store. */
    public static boolean storable(String value) {
        return value.indexOf('\u0000') < 0 && strictUtf8(value) != null;
    }

    /**
     * Python {@code json.dumps(value, ensure_ascii=False)} for one string: the quoted form whose UTF-8 bytes the S2-1
     * ledger hashes as {@code sourceHash}. Only {@code "} {@code \}, the five short escapes and the other C0 controls
     * are escaped (lowercase hex); everything else, including DEL, U+2028 and non-BMP characters, stays verbatim.
     */
    public static String pythonJsonString(String value) {
        StringBuilder out = new StringBuilder(value.length() + 16).append('"');
        for (int index = 0; index < value.length(); index++) {
            char c = value.charAt(index);
            switch (c) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\b' -> out.append("\\b");
                case '\f' -> out.append("\\f");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
                }
            }
        }
        return out.append('"').toString();
    }

    /**
     * The substring of {@code text} between two Unicode code point offsets ({@code end} exclusive), or {@code null} when the
     * range is not {@code 0 <= start < end <= codePoints(text)}. Offsets are code points, never UTF-16 units.
     */
    public static String codePointSlice(String text, long start, long end) {
        int length = codePoints(text);
        if (start < 0 || start >= end || end > length) {
            return null;
        }
        int from = text.offsetByCodePoints(0, (int) start);
        int to = text.offsetByCodePoints(from, (int) (end - start));
        return text.substring(from, to);
    }
}
