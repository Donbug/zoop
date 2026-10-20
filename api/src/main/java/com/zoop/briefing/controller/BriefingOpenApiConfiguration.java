package com.zoop.briefing.controller;

import java.util.List;

import io.swagger.v3.core.converter.ModelConverters;
import io.swagger.v3.oas.models.Components;
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
        };
    }
}
