package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** Reconstructs the complete provider contract. A true-only verifier is not independent validation. */
final class BriefingCompanySchemas {
    private BriefingCompanySchemas() { }
    static ObjectNode format(String prefix, String phase, StrictJson.Obj frozen) {
        if (!Set.of("company_outlook_", "company_reading_").contains(prefix) || !Set.of("generation", "verification").contains(phase))
            throw new IllegalArgumentException("Unsupported company response schema");
        List<String> ids = frozen.objects("targets").stream().map(t -> t.string("companyId")).toList();
        List<String> evidence = new ArrayList<>(frozen.object("sources").node().propertyNames()); Collections.sort(evidence);
        ObjectNode fields = StrictJson.newObject(); fields.set("companyId", choice(ids));
        if ("verification".equals(phase)) {
            fields.set("supported", StrictJson.newObject().put("type", "boolean"));
            fields.set("reason", text(700));
        } else if ("company_reading_".equals(prefix)) {
            fields.set("brief", statement(evidence, 70)); fields.set("watch", statement(evidence, 50)); fields.set("change", statement(evidence, 60));
        } else {
            ObjectNode s = statement(evidence, 420);
            fields.set("assessment", choice(List.of("positive", "negative", "mixed", "watch")));
            fields.set("impact", s); fields.set("outlook", s);
            fields.set("conditions", array(s, 1, 3)); fields.set("risks", array(s, 1, 3));
            ObjectNode comparison = s.deepCopy();
            ObjectNode props = (ObjectNode) comparison.path("properties");
            props.set("status", choice(List.of("updated", "compared", "unavailable")));
            ObjectNode nullable = StrictJson.newObject(); nullable.putArray("type").add("string").add("null");
            props.set("previousResultVersion", nullable); fields.set("comparison", object(props));
        }
        ObjectNode outer = StrictJson.newObject();
        outer.set("verification".equals(phase) ? "checks" : "companies", array(object(fields), ids.size(), ids.size()));
        ObjectNode format = StrictJson.newObject().put("type", "json_schema").put("name", prefix + phase).put("strict", true);
        format.set("schema", object(outer)); return format;
    }
    private static ObjectNode object(ObjectNode properties) {
        ObjectNode schema = StrictJson.newObject().put("type", "object"); schema.set("properties", properties);
        var required = schema.putArray("required"); properties.propertyNames().forEach(required::add);
        schema.put("additionalProperties", false); return schema;
    }
    private static ObjectNode text(int maximum) { return StrictJson.newObject().put("type", "string").put("minLength", 1).put("maxLength", maximum); }
    private static ObjectNode choice(List<String> values) {
        ObjectNode schema = StrictJson.newObject().put("type", "string"); var options = schema.putArray("enum"); values.forEach(options::add); return schema;
    }
    private static ObjectNode array(JsonNode item, int minimum, int maximum) {
        ObjectNode schema = StrictJson.newObject().put("type", "array"); schema.set("items", item);
        return schema.put("minItems", minimum).put("maxItems", maximum);
    }
    private static ObjectNode statement(List<String> evidence, int maximum) {
        ObjectNode props = StrictJson.newObject(); props.set("text", text(maximum));
        props.set("evidenceIds", array(choice(evidence), 1, 6)); return object(props);
    }
}
