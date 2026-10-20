package com.zoop.briefing.controller;

import java.util.List;
import java.util.Set;

import io.swagger.v3.core.converter.ModelConverters;
import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.media.Schema;
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
        };
    }
}
