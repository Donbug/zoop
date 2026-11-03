package com.zoop.admin.transcripts;

import static org.junit.jupiter.api.Assertions.*;
import io.swagger.v3.core.converter.ModelConverters;
import io.swagger.v3.oas.models.media.Schema;
import org.junit.jupiter.api.Test;

/** A-ADM-02b: publishing these DTOs must not reuse generic statistics Summary/Feedback schemas. */
class TranscriptSchemaTest {
    @Test void listPublishesTheContractNamesAndRequiredFields() {
        var schemas = ModelConverters.getInstance().readAll(TranscriptHttpSchemas.Page.class);
        var page = schemas.get("TranscriptPage");
        assertNotNull(page);
        assertTrue(page.getRequired().containsAll(java.util.List.of("items", "nextCursor", "total")));
        var items = (Schema<?>) page.getProperties().get("items");
        assertEquals("#/components/schemas/TranscriptSummary", items.getItems().get$ref());
        assertNotNull(schemas.get("TranscriptSummary"));
        assertFalse(schemas.containsKey("Summary"));
    }

    @Test void detailKeepsMaskingAndFeedbackSeparateFromStatisticsModels() {
        var schemas = ModelConverters.getInstance().readAll(TranscriptHttpSchemas.Detail.class);
        assertNotNull(schemas.get("TranscriptDetail"));
        assertNotNull(schemas.get("TranscriptMessage"));
        assertNotNull(schemas.get("TranscriptFeedback"));
        assertTrue(schemas.get("MaskingReport").getRequired().contains("completed"));
        var feedback = (Schema<?>) schemas.get("TranscriptMessage").getProperties().get("feedback");
        assertEquals("#/components/schemas/TranscriptFeedback", feedback.get$ref());
        assertFalse(schemas.containsKey("Feedback"));
    }
}
