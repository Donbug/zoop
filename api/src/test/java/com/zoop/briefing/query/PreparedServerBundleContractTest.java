package com.zoop.briefing.query;

import com.zoop.briefing.storage.BriefingRound;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.LocalDate;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import tools.jackson.databind.json.JsonMapper;
import static org.junit.jupiter.api.Assertions.*;

/** External private records are validated, never embedded in tests or disclosed. */
@EnabledIfEnvironmentVariable(named="BRIEFING_SERVER_BUNDLE",matches=".+")
class PreparedServerBundleContractTest {
    private final JsonMapper json=JsonMapper.builder().build();
    @Test void twelveCommonSnapshotsSatisfyThe553ReadContractWithoutPublication() throws Exception {
        var root=Path.of(System.getenv("BRIEFING_SERVER_BUNDLE"));
        int count=0;
        for(String line:Files.readAllLines(root.resolve("tables/briefing_rounds.jsonl"))) {
            var value=json.readTree(line);
            var generated=Instant.parse(value.path("generated_at").asString());
            // In-memory DTO validation only. Real staged rows remain unpublished.
            var row=new BriefingRound(value.path("id").asString(),LocalDate.parse(value.path("round_date").asString()),
                value.path("edition").asString(),Instant.parse(value.path("scheduled_at").asString()),
                value.path("window_from").isNull()?null:Instant.parse(value.path("window_from").asString()),
                Instant.parse(value.path("window_to").asString()),value.path("open_start").asBoolean(),"published",generated,
                generated,null,value.path("published_payload"),value.path("public_snapshot"),value.get("comparison_snapshot"));
            assertEquals("scheduled",value.path("status").asString());assertTrue(value.path("published_at").isNull());
            BriefingSnapshotValidator.validate(row,true);
            var contexts=value.path("public_snapshot").path("priorityContext");
            assertTrue(contexts.path("originalReferenceIds").size()>0);
            for(var ref:value.path("public_snapshot").path("prioritySummary").path("evidenceIds"))
                assertFalse(ref.asString().startsWith("context:"));
            count++;
        }
        assertEquals(12,count);
    }
}
