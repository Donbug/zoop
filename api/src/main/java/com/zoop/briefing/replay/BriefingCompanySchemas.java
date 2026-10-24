package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** Reconstructs the complete provider contract. A true-only verifier is not independent validation. */
final class BriefingCompanySchemas {
    private BriefingCompanySchemas() { }
    static ObjectNode format(String prefix, String phase, StrictJson.Obj frozen) {
        if ("judgment_update_".equals(prefix)) return BriefingJudgmentUpdateRules.format(phase, frozen);
        if (!Set.of("company_outlook_", "company_reading_", "company_card_").contains(prefix) || !Set.of("generation", "verification").contains(phase))
            throw new IllegalArgumentException("Unsupported company response schema");
        List<String> ids = frozen.objects("targets").stream().map(t -> t.string("companyId")).toList();
        List<String> evidence = new ArrayList<>(frozen.object("sources").node().propertyNames()); Collections.sort(evidence);
        ObjectNode fields = StrictJson.newObject(); fields.set("companyId", choice(ids));
        boolean card = "company_card_".equals(prefix);
        if ("verification".equals(phase)) {
            fields.set("supported", StrictJson.newObject().put("type", "boolean"));
            fields.set("reason", text(700));
            if (card || ("company_reading_".equals(prefix) && (frozen.has("schemaVersion") && "zoop-company-reading-v2".equals(frozen.string("schemaVersion"))))) {
                ObjectNode quality = StrictJson.newObject();
                for (String key : card ? List.of("concise", "distinctRoles", "qualifiersPreserved", "noUnsupportedClaim") : List.of("specificity", "newInformation", "continuity", "nonRepetition"))
                    quality.set(key, StrictJson.newObject().put("type", "boolean"));
                fields.set("quality", object(quality));
            }
        } else if (card) {
            fields.set("topic", statement(evidence, 12)); fields.set("title", statement(evidence, 32));
            fields.set("description", statement(evidence, 64));
        } else if ("company_reading_".equals(prefix)) {
            if ((frozen.has("schemaVersion") && "zoop-company-reading-v2".equals(frozen.string("schemaVersion")))) {
                fields.set("brief", statement(evidence, 140)); fields.set("fact", statement(evidence, 160));
                fields.set("watch", statement(evidence, 180)); fields.set("background", statement(evidence, 240));
                fields.set("change", statement(evidence, 180));
            } else {
                fields.set("brief", statement(evidence, 70)); fields.set("watch", statement(evidence, 50)); fields.set("change", statement(evidence, 60));
            }
        } else {
            ObjectNode s = statement(evidence, 420);
            fields.set("assessment", choice(List.of("positive", "negative", "mixed", "watch")));
            fields.set("impact", s); fields.set("outlook", s);
            fields.set("conditions", array(s, 1, 3)); fields.set("risks", array(s, 1, 3));
            ObjectNode comparison = s.deepCopy();
            ObjectNode props = (ObjectNode) comparison.path("properties");
            List<String> statuses = List.of("updated", "compared", "unavailable");
            if (frozen.has("comparisonContract")) {
                if (!"edition-bound-v2".equals(frozen.string("comparisonContract"))) throw new IllegalArgumentException("Company comparison contract");
                statuses = "morning".equals(frozen.string("edition")) ? List.of("updated", "unavailable") : List.of("compared", "unavailable");
            }
            props.set("status", choice(statuses));
            ObjectNode nullable = StrictJson.newObject(); nullable.putArray("type").add("string").add("null");
            props.set("previousResultVersion", nullable); fields.set("comparison", object(props));
        }
        ObjectNode outer = StrictJson.newObject();
        outer.set("verification".equals(phase) ? "checks" : "companies", array(object(fields), ids.size(), ids.size()));
        ObjectNode format = StrictJson.newObject().put("type", "json_schema").put("name", prefix + phase).put("strict", true);
        format.set("schema", object(outer)); return format;
    }
    static ObjectNode object(ObjectNode properties) {
        ObjectNode schema = StrictJson.newObject().put("type", "object"); schema.set("properties", properties);
        var required = schema.putArray("required"); properties.propertyNames().forEach(required::add);
        schema.put("additionalProperties", false); return schema;
    }
    static ObjectNode text(int maximum) { return StrictJson.newObject().put("type", "string").put("minLength", 1).put("maxLength", maximum); }
    static ObjectNode choice(List<String> values) {
        ObjectNode schema = StrictJson.newObject().put("type", "string"); var options = schema.putArray("enum"); values.forEach(options::add); return schema;
    }
    static ObjectNode array(JsonNode item, int minimum, int maximum) {
        ObjectNode schema = StrictJson.newObject().put("type", "array"); schema.set("items", item);
        return schema.put("minItems", minimum).put("maxItems", maximum);
    }
    static ObjectNode statement(List<String> evidence, int maximum) {
        ObjectNode props = StrictJson.newObject(); props.set("text", text(maximum));
        props.set("evidenceIds", array(choice(evidence), 1, 6)); return object(props);
    }
}
