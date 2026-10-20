package com.zoop.document.evidence.service;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Set;

import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.json.StrictJson;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.document.evidence.controller.EvidenceController;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import tools.jackson.databind.JsonNode;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** The public contract of {@code getEvidence}: route, keys (all serialized, none added), headers and the error envelope. */
class EvidenceControllerTest {
    private static final Set<String> RESPONSE_KEYS = Set.of("id", "quote", "start", "end", "articleId", "articleVersion", "article",
            "quoteVerified", "eventIds", "metadata", "sentiment", "documentVersion", "documentSummary", "analysisStatus",
            "analysisProvenance", "resultVersion");
    private static final Set<String> METADATA_KEYS = Set.of("source", "asOf", "graphVersion", "requestId", "partial", "failures");
    private static final Set<String> FAILURE_KEYS = Set.of("section", "code", "message", "retryable", "asOf");
    private static final Set<String> ARTICLE_KEYS = Set.of("title", "publisher", "url", "publishedAt");

    @TempDir
    Path temp;

    private MockMvc mvc(EvidenceWorld world) {
        return MockMvcBuilders.standaloneSetup(new EvidenceController(world.service()))
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter())
                .build();
    }

    private static JsonNode body(MvcResult result) throws Exception {
        return StrictJson.parseObject(result.getResponse().getContentAsString(java.nio.charset.StandardCharsets.UTF_8)).node();
    }

    @Test
    void serializesEveryContractKeyIncludingNullsAndAddsNone() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();

        MvcResult result = mvc(world).perform(get("/api/v1/evidence/" + world.evidenceId).header(RequestIdFilter.HEADER, "req-ev"))
                .andExpect(status().isOk())
                .andExpect(header().string(RequestIdFilter.HEADER, "req-ev"))
                .andExpect(jsonPath("$.id").value(world.evidenceId))
                .andExpect(jsonPath("$.quote").value(EvidenceWorld.QUOTE))
                .andExpect(jsonPath("$.start").value(5))
                .andExpect(jsonPath("$.end").value(9))
                .andExpect(jsonPath("$.quoteVerified").value(true))
                .andExpect(jsonPath("$.metadata.source").value("document-analysis"))
                .andExpect(jsonPath("$.metadata.asOf").value("2026-10-15T01:00:00Z"))
                .andExpect(jsonPath("$.metadata.requestId").value("req-ev"))
                .andExpect(jsonPath("$.metadata.partial").value(true))
                .andExpect(jsonPath("$.metadata.failures[0].section").value("eventIds"))
                .andExpect(jsonPath("$.metadata.failures[0].code").value("SOURCE_UNAVAILABLE"))
                .andExpect(jsonPath("$.metadata.failures[0].retryable").value(false))
                .andExpect(jsonPath("$.article.publishedAt").value("2026-10-15T00:00:00Z"))
                .andExpect(jsonPath("$.documentSummary.resultVersion").value("result-1"))
                .andExpect(jsonPath("$.resultVersion").value("result-1"))
                .andReturn();

        JsonNode body = body(result);
        assertEquals(RESPONSE_KEYS, Set.copyOf(body.propertyNames()));
        assertEquals(METADATA_KEYS, Set.copyOf(body.get("metadata").propertyNames()));
        assertEquals(FAILURE_KEYS, Set.copyOf(body.get("metadata").get("failures").get(0).propertyNames()));
        assertEquals(ARTICLE_KEYS, Set.copyOf(body.get("article").propertyNames()));
        for (String nullKey : List.of("sentiment", "analysisStatus")) {
            assertTrue(body.get(nullKey).isNull(), nullKey);
        }
        assertTrue(body.get("metadata").get("graphVersion").isNull());
        assertTrue(body.get("metadata").get("failures").get(0).get("asOf").isNull());
        assertTrue(body.get("eventIds").isArray() && body.get("eventIds").isEmpty());
    }

    @Test
    void aWithheldSummaryStillSerializesItsKeysAsNull() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        world.read.summaries.add(new com.zoop.document.evidence.repository.SummaryView("an-3", EvidenceWorld.ARTICLE, EvidenceWorld.VERSION,
                "summary", null, "pending", 2, EvidenceWorld.GRANT, EvidenceWorld.REVISION, "job-3", null, null, null, null, null));

        JsonNode body = body(mvc(world).perform(get("/api/v1/evidence/" + world.evidenceId)).andExpect(status().isOk()).andReturn());

        assertEquals(RESPONSE_KEYS, Set.copyOf(body.propertyNames()));
        for (String key : List.of("documentSummary", "analysisProvenance", "resultVersion")) {
            assertTrue(body.get(key).isNull(), key);
        }
    }

    @Test
    void errorsUseTheEnvelopeAndTheRequestId() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        MockMvc mvc = mvc(world);
        String path = "/api/v1/evidence/" + world.evidenceId;

        mvc.perform(get("/api/v1/evidence/ev-" + "0".repeat(64)).header(RequestIdFilter.HEADER, "r1"))
                .andExpect(status().isNotFound())
                .andExpect(header().string(RequestIdFilter.HEADER, "r1"))
                .andExpect(jsonPath("$.error.code").value("RESOURCE_NOT_FOUND"))
                .andExpect(jsonPath("$.error.requestId").value("r1"));
        mvc.perform(get(path).param("round", "brf-1")).andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("VERSION_UNAVAILABLE"))
                .andExpect(jsonPath("$.error.retryable").value(false));
        mvc.perform(get(path).param("graphVersion", "gv-1")).andExpect(status().isConflict());
        mvc.perform(get(path).param("asOf", "2026-10-15T00:00:00Z")).andExpect(status().isConflict());
        mvc.perform(get(path).param("asOf", "2026-10-15T00:00:00")).andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
        mvc.perform(get(path).param("companyId", "")).andExpect(status().isUnprocessableEntity());
        mvc.perform(get(path).param("companyId", "NOPE")).andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("RESOURCE_NOT_FOUND"));

        world.registry.setAccessStatus(EvidenceWorld.ARTICLE, "private");
        mvc.perform(get(path)).andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("EVIDENCE_UNAVAILABLE"))
                .andExpect(jsonPath("$.error.retryable").value(false));
        world.registry.setAccessStatus(EvidenceWorld.ARTICLE, "available");

        Files.delete(world.grants);
        mvc.perform(get(path)).andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error.code").value("SOURCE_UNAVAILABLE"))
                .andExpect(jsonPath("$.error.retryable").value(true));
    }

    @Test
    void theEvidenceDeniedBodyNeverNamesAReasonOrALocation() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        world.writeGrants(EvidenceWorld.grant(EvidenceWorld.GRANT, "r2", EvidenceWorld.PROVIDER, true, "known",
                List.of("read", "store", "model-send", "quote-display"), List.of("authored-replay"),
                List.of(EvidenceWorld.SUMMARY, EvidenceWorld.VERIFIER), null));

        String text = mvc(world).perform(get("/api/v1/evidence/" + world.evidenceId)).andExpect(status().isNotFound()).andReturn()
                .getResponse().getContentAsString(java.nio.charset.StandardCharsets.UTF_8);

        assertEquals(Set.of("error"), Set.copyOf(StrictJson.parseObject(text).node().propertyNames()));
        assertTrue(!text.contains("grant") && !text.contains(world.grants.toString()) && !text.contains(world.root.toString()), text);
    }
}
