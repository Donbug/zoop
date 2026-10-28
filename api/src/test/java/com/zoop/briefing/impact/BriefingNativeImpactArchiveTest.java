package com.zoop.briefing.impact;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import tools.jackson.databind.json.JsonMapper;
import static org.junit.jupiter.api.Assertions.*;

/** Explicit opt-in, read-only offline replay. No private fixture is distributed with this test. */
@EnabledIfEnvironmentVariable(named="ZOOP_TEST_NATIVE_IMPACT_ARCHIVE",matches=".+")
class BriefingNativeImpactArchiveTest {
    @Test void replaysSavedRequestsNativeAnswersAndSupplementalChecksWithoutProviderAccess() throws Exception {
        Path manifest=Path.of(System.getenv("ZOOP_TEST_NATIVE_IMPACT_ARCHIVE")).toRealPath(),root=manifest.getParent();
        var mapper=JsonMapper.builder().build();var data=StrictJson.parseObject(Files.readAllBytes(manifest)).node();int count=0;
        for(var row:data.path("reviews")) {
            List<BriefingNativeImpactPolicy.Proof> proofs=new ArrayList<>();String title=null;
            for(var proof:row.path("proofs")) {
                byte[] raw=Files.readAllBytes(root.resolve(proof.path("path").asString()));
                assertEquals(proof.path("sha256").asString(),Canonical.sha256(raw));
                var receipt=mapper.readTree(raw);var request=BriefingNativeImpactPolicy.request(root,proof,receipt);
                proofs.add(new BriefingNativeImpactPolicy.Proof(receipt,request));
                if("impact".equals(receipt.path("stage").asString()))title=BriefingNativeImpactPolicy.generationInput(request)
                        .path("relation").path("object").path("names").get(0).asString();
            }
            assertNotNull(title);var basis=row.path("basis");Instant cutoff=Instant.parse(basis.path("dataAsOf").asString());
            for(var assessment:row.path("assessments")) {
                BriefingNativeImpactPolicy.assessment(assessment,basis,title,proofs,row.has("citationRepair"));
                for(var q:assessment.path("facts"))BriefingImpactReviewService.sourceQuote(q,basis,cutoff);
                for(var q:assessment.path("evidence"))BriefingImpactReviewService.sourceQuote(q,basis,cutoff);
                if(assessment.has("supplementalReview"))BriefingSupplementalReviewReader.read(assessment.path("supplementalReview"),row,
                        assessment,root,assessment.path("companyId").asString(),title,Clock.systemUTC(),mapper);
                count++;
            }
        }
        assertTrue(count>0);System.out.println("Offline native impact assessments checked: "+count+"; provider calls: 0");
    }
}
