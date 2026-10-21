package com.zoop.briefing.controller;

import java.util.List;
import java.util.Set;
import java.util.ArrayList;

import io.swagger.v3.core.converter.ModelConverters;
import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.media.Schema;
import io.swagger.v3.oas.models.media.StringSchema;
import org.springdoc.core.customizers.OpenApiCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** JSON snapshot union annotations emit references; register their documentation types explicitly. */
@Configuration
public class BriefingOpenApiConfiguration {
    @Bean
    public OpenApiCustomizer briefingSnapshotSchemas() {
        return openApi -> {
            if (openApi.getComponents() == null) openApi.setComponents(new Components());
            boolean version31 = openApi.getOpenapi() != null && openApi.getOpenapi().startsWith("3.1");
            for (Class<?> type : List.of(BriefingHttpSchemas.AnalysisSummary.class,
                    BriefingHttpSchemas.MarketVariables.class, BriefingHttpSchemas.SinceMorning.class,
                    BriefingHttpSchemas.PreviousComparison.class)) {
                ModelConverters.getInstance(version31).readAll(type).forEach(openApi.getComponents()::addSchemas);
            }
            // A nullable record reference otherwise becomes {$ref: ..., type: "null"}
            // in 3.1, which rejects every actual non-null analysis object.
            Schema<?> analysis = new Schema<>().$ref("#/components/schemas/MarketOutlookAnalysis");
            if (version31) {
                Schema<?> nullValue = new Schema<>();
                nullValue.setTypes(Set.of("null"));
                analysis = new Schema<>().anyOf(List.of(analysis, nullValue));
            } else {
                analysis = new Schema<>().allOf(List.of(analysis)).nullable(true);
            }
            openApi.getComponents().getSchemas().get("AnalysisSummary").addProperty("analysis", analysis);
            Schema<?> claim = openApi.getComponents().getSchemas().get("MarketOutlookClaim");
            claim.addProperty("direction", nullableEnum(version31, List.of("up", "down", "flat", "uncertain")));
            claim.addProperty("updateAction", nullableEnum(version31, List.of("maintain", "strengthen", "weaken", "withdraw")));
        };
    }

    private static Schema<?> nullableEnum(boolean version31, List<String> allowed) {
        StringSchema value = new StringSchema();
        value.setEnum(allowed);
        if (version31) {
            Schema<?> nullValue = new Schema<>();
            nullValue.setTypes(Set.of("null"));
            return new Schema<>().anyOf(List.of(value, nullValue));
        }
        var nullableValues = new ArrayList<>(allowed);
        nullableValues.add(null);
        value.setEnum(nullableValues);
        return value.nullable(true);
    }
}
