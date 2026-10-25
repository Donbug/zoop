package com.zoop.ai.http;

import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.ai.PipelineJob;
import com.zoop.ai.extraction.ExtractionSubmission;
import com.zoop.ai.http.WireJson.Malformed;
import com.zoop.ai.http.WireJson.Obj;
import com.zoop.ai.plan.PlanAdmission;
import com.zoop.ai.plan.PlanIdentity;
import com.zoop.ai.plan.PlanManifest;
import com.zoop.ai.plan.PlanReference;
import com.zoop.ai.relation.RelationSubmission;
import com.zoop.ai.relation.RelationUpstream;
import tools.jackson.databind.JsonNode;

/** Closed, request-bound admission decoding, including canonical manifest and deterministic identity verification. */
final class PlanAdmissionWire {
    private static final Pattern ID = Pattern.compile("(?!\\.\\.?$)[A-Za-z0-9_.-]{1,120}");
    private static final Pattern CODE = Pattern.compile("[a-z][a-z0-9_]{0,79}");
    private static final Pattern ROUND_ID = Pattern.compile("(?s).{1,200}");
    private static final Pattern ADMISSION_ID = Pattern.compile("pa-[0-9a-f]{64}");

    private PlanAdmissionWire() {
    }

    static PlanAdmission admission(JsonNode document, PlanReference requested) {
        try {
            Obj root = closed(document, "admission", "schemaVersion", "admissionId", "acceptedAt", "policyRevision", "policyDigest", "manifest", "authority");
            PipelineWire.schema(root, PlanReference.SCHEMA_VERSION);
            Obj manifest = closed(root.raw("manifest"), "manifest", "schemaVersion", "planId", "planDigest", "receiptSha256", "principal", "round", "provenance", "units", "manifestDigest");
            PipelineWire.schema(manifest, PlanManifest.SCHEMA_VERSION);
            PlanReference reference = new PlanReference(manifest.string("planId", PlanReference.PLAN_ID), manifest.string("planDigest", Obj.SHA256));
            if (!requested.equals(reference)) {
                throw new Malformed("manifest.reference");
            }
            String manifestDigest = manifest.string("manifestDigest", Obj.SHA256);
            if (!manifestDigest.equals(PlanIdentity.sha256(canonical(manifest.node(), true)))) {
                throw new Malformed("manifest.manifestDigest");
            }
            Obj round = closed(manifest.raw("round"), "manifest.round", "sourceId", "roundId", "ingestionInputDigest");
            PipelineJob.Provenance provenance = provenance(manifest.raw("provenance"), "manifest.provenance");
            var units = new ArrayList<PlanManifest.Unit>();
            for (JsonNode node : manifest.array("units", Integer.MAX_VALUE)) {
                Obj unit = closed(node, "manifest.units[]", "unitKey", "extractionSubmit", "extractionInputDigest", "relationSubmit");
                Obj extraction = closed(unit.raw("extractionSubmit"), "unit.extractionSubmit", "schemaVersion", "jobId", "approvedRequestDigest");
                PipelineWire.schema(extraction, ExtractionSubmission.SCHEMA_VERSION);
                Obj relation = closed(unit.raw("relationSubmit"), "unit.relationSubmit", "schemaVersion", "jobId", "provenance", "upstream");
                PipelineWire.schema(relation, RelationSubmission.SCHEMA_VERSION);
                PipelineJob.Provenance relationProvenance = provenance(relation.raw("provenance"), "unit.relationSubmit.provenance");
                Obj upstream = closed(relation.raw("upstream"), "unit.relationSubmit.upstream", "jobId", "inputDigest");
                units.add(new PlanManifest.Unit(unit.string("unitKey", ID),
                        new ExtractionSubmission(extraction.string("jobId", ID), extraction.string("approvedRequestDigest", Obj.SHA256), provenance.executionMode()),
                        unit.string("extractionInputDigest", Obj.SHA256),
                        new RelationSubmission(relation.string("jobId", ID), relationProvenance.sourceKind(), relationProvenance.executionMode(),
                                new RelationUpstream(upstream.string("jobId", ID), upstream.string("inputDigest", Obj.SHA256)))));
            }
            PlanManifest value = new PlanManifest(reference, manifest.string("receiptSha256", Obj.SHA256), manifest.string("principal", PlanIdentity.PRINCIPAL),
                    new PlanManifest.Round(round.string("sourceId", ROUND_ID), round.string("roundId", ROUND_ID), round.string("ingestionInputDigest", Obj.SHA256)),
                    provenance, units, manifestDigest);
            Obj authority = closed(root.raw("authority"), "authority", "state", "reason");
            PlanAdmission.Authority current = new PlanAdmission.Authority(authority.choice("state", PipelineWire.parser(PlanAdmission.State.class)), authority.optString("reason", CODE));
            String stamp = root.string("acceptedAt", Obj.PRINTABLE);
            var acceptedAt = java.time.OffsetDateTime.parse(stamp);
            if (acceptedAt.getOffset().getTotalSeconds() != 0) {
                throw new Malformed("admission.acceptedAt");
            }
            return new PlanAdmission(root.string("admissionId", ADMISSION_ID), acceptedAt.toInstant(),
                    root.count("policyRevision"), root.string("policyDigest", Obj.SHA256), value, current);
        } catch (IllegalArgumentException | DateTimeParseException error) {
            throw new Malformed("admission");
        }
    }

    static PipelineWire.Rejection rejection(JsonNode document, String requestId) {
        Obj root = closed(document, "error", "schemaVersion", "error");
        Obj error = root.object("error");
        Set<String> allowed = Set.of("code", "retryable", "requestId", "runtimeCode", "field");
        if (error.node().properties().stream().anyMatch(entry -> !allowed.contains(entry.getKey()))) {
            throw new Malformed("error");
        }
        PipelineWire.schema(root, PlanReference.SCHEMA_VERSION);
        if (!requestId.equals(error.string("requestId", AnalysisWire.REQUEST_ID))) {
            throw new Malformed("error.requestId");
        }
        return new PipelineWire.Rejection(root, error.string("code", CODE), error.bool("retryable"),
                optional(error, "runtimeCode"), optional(error, "field"));
    }

    private static java.util.Optional<String> optional(Obj object, String key) {
        return object.node().get(key) == null ? java.util.Optional.empty() : object.optString(key, AnalysisWire.TEXT);
    }

    private static PipelineJob.Provenance provenance(JsonNode node, String path) {
        return PipelineWire.provenance(closed(node, path, "sourceKind", "executionMode", "recordingKind"));
    }

    private static Obj closed(JsonNode node, String path, String... keys) {
        Obj object = Obj.of(node, path);
        Set<String> required = Set.of(keys);
        if (node.size() != required.size() || node.properties().stream().anyMatch(entry -> !required.contains(entry.getKey()))) {
            throw new Malformed(path);
        }
        return object;
    }

    /** Python canonical JSON for this closed schema: sorted ASCII keys, literal Unicode and no whitespace/newline. */
    static String canonical(JsonNode node, boolean omitManifestDigest) {
        StringBuilder out = new StringBuilder();
        canonical(node, out, omitManifestDigest);
        return out.toString();
    }

    private static void canonical(JsonNode node, StringBuilder out, boolean omitManifestDigest) {
        if (node.isObject()) {
            out.append('{');
            boolean first = true;
            for (var entry : node.properties().stream().sorted(java.util.Map.Entry.comparingByKey()).toList()) {
                if (omitManifestDigest && entry.getKey().equals("manifestDigest")) {
                    continue;
                }
                if (!first) {
                    out.append(',');
                }
                first = false;
                quote(entry.getKey(), out);
                out.append(':');
                canonical(entry.getValue(), out, false);
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
                canonical(item, out, false);
            }
            out.append(']');
        } else if (node.isString()) {
            quote(node.stringValue(), out);
        } else {
            // Manifests contain only strings, objects and arrays. Never reinterpret unexpected numbers/null/bools.
            throw new Malformed("manifest");
        }
    }

    private static void quote(String text, StringBuilder out) {
        out.append('"');
        for (int index = 0; index < text.length(); index++) {
            char c = text.charAt(index);
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
                        out.append("\\u00").append(Character.forDigit(c >> 4, 16)).append(Character.forDigit(c & 15, 16));
                    } else if (Character.isHighSurrogate(c)) {
                        if (++index >= text.length() || !Character.isLowSurrogate(text.charAt(index))) {
                            throw new Malformed("manifest.encoding");
                        }
                        out.append(c).append(text.charAt(index));
                    } else if (Character.isLowSurrogate(c)) {
                        throw new Malformed("manifest.encoding");
                    } else {
                        out.append(c);
                    }
                }
            }
        }
        out.append('"');
    }
}
