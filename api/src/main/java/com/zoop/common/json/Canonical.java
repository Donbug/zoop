package com.zoop.common.json;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HexFormat;
import java.util.List;

import tools.jackson.databind.JsonNode;

/**
 * The canonical JSON of the AI runtime: Python {@code json.dumps(value, ensure_ascii=False, sort_keys=True,
 * separators=(",", ":"))}, whose UTF-8 bytes the worker hashes into every identity ({@code digest}). Reproducing it exactly
 * is what lets the app recompute artifact ids, result versions and model-configuration revisions instead of trusting them.
 *
 * <p>{@link #write} is the Python-parity form. It accepts objects with ASCII keys only (Python sorts keys by code point and
 * Java by UTF-16 unit, which agree for ASCII), arrays, strings with a UTF-8 form, booleans, null and integers, and rejects
 * everything else, in particular floating-point numbers, whose Python and Java text forms differ. {@link #writeApp} is the
 * app's own deterministic form for documents only this app reads back (receipts): the same, but a finite floating-point
 * number is written with {@link Double#toString(double)}. Both throw {@link StrictJson.Malformed}.
 */
public final class Canonical {
    private Canonical() {
    }

    public static String write(JsonNode node) {
        StringBuilder out = new StringBuilder();
        append(out, node, false);
        return out.toString();
    }

    public static String writeApp(JsonNode node) {
        StringBuilder out = new StringBuilder();
        append(out, node, true);
        return out.toString();
    }

    public static byte[] bytes(JsonNode node) {
        return write(node).getBytes(StandardCharsets.UTF_8);
    }

    public static byte[] appBytes(JsonNode node) {
        return writeApp(node).getBytes(StandardCharsets.UTF_8);
    }

    /** Lowercase hex SHA-256 of the canonical UTF-8 text: the worker's {@code digest()}. */
    public static String digest(JsonNode node) {
        return sha256(bytes(node));
    }

    public static String sha256(byte[] content) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content));
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 is unavailable", error);
        }
    }

    public static String sha256(String text) {
        return sha256(text.getBytes(StandardCharsets.UTF_8));
    }

    private static void append(StringBuilder out, JsonNode node, boolean allowFloats) {
        if (node == null || node.isNull()) {
            out.append("null");
        } else if (node.isObject()) {
            List<String> keys = new ArrayList<>(node.propertyNames());
            for (String key : keys) {
                if (!ascii(key)) {
                    throw new StrictJson.Malformed();
                }
            }
            Collections.sort(keys);
            out.append('{');
            boolean first = true;
            for (String key : keys) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                out.append(Text.pythonJsonString(key)).append(':');
                append(out, node.get(key), allowFloats);
            }
            out.append('}');
        } else if (node.isArray()) {
            out.append('[');
            boolean first = true;
            for (JsonNode item : node.values()) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                append(out, item, allowFloats);
            }
            out.append(']');
        } else if (node.isString()) {
            String value = node.stringValue();
            if (Text.strictUtf8(value) == null) {
                throw new StrictJson.Malformed();
            }
            out.append(Text.pythonJsonString(value));
        } else if (node.isBoolean()) {
            out.append(node.booleanValue() ? "true" : "false");
        } else if (node.isIntegralNumber()) {
            out.append(node.bigIntegerValue().toString());
        } else if (node.isNumber() && allowFloats && Double.isFinite(node.doubleValue())) {
            out.append(Double.toString(node.doubleValue()));
        } else {
            throw new StrictJson.Malformed();
        }
    }

    private static boolean ascii(String key) {
        for (int index = 0; index < key.length(); index++) {
            if (key.charAt(index) > 0x7f) {
                return false;
            }
        }
        return true;
    }
}
