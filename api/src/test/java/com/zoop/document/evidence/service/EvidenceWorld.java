package com.zoop.document.evidence.service;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Set;
import java.util.function.Consumer;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.repository.AnalysisIdentity;
import com.zoop.document.evidence.repository.EvidenceView;
import com.zoop.document.evidence.repository.SummaryView;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.VersionRow;
import com.zoop.document.service.InMemoryDocumentRegistry;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * One synthetic document with one settled summary and one cited body quote. {@link #normal()} is the usual case (the analysis made
 * its own calls); {@link #cached()} is a summary served from the artifact cache: its calls are recorded under another job and
 * only its exact receipt file, written with a real {@link ArtifactFileStore}, names that job.
 */
final class EvidenceWorld {
    static final Instant NOW = Instant.parse("2026-10-15T01:00:00Z");
    static final String ARTICLE = "art-1";
    static final String VERSION = "v1";
    static final String PROVIDER = "src";
    static final String GRANT = "g1";
    static final String REVISION = "r1";
    static final String TEXT = "text-1";
    static final String TEXT_SHA = "a".repeat(64);
    static final String INPUT_DIGEST = "b".repeat(64);
    static final String QUOTE = "\uD83D\uDE00 첫째";
    static final long START = 5;
    static final long END = 9;
    static final String SUMMARY = "document-summary";
    static final String VERIFIER = "semantic-verification";

    final Path directory;
    final Path grants;
    final Path root;
    final InMemoryDocumentRegistry registry = new InMemoryDocumentRegistry();
    final InMemoryEvidenceRead read = new InMemoryEvidenceRead();
    final ArtifactFileStore store;
    String evidenceId;

    EvidenceWorld(Path directory) throws IOException {
        this.directory = directory.toRealPath();
        this.grants = this.directory.resolve("grants.json");
        this.root = Files.createDirectory(this.directory.resolve("artifacts"));
        this.store = ArtifactFileStore.at(root);
        registry.seedArticle(ARTICLE, "news", PROVIDER, null, "available");
        registry.insertArtifactIfAbsent(new ArtifactRow(TEXT, "extracted_text", "artifact-root:extracted_text/text-1.txt", TEXT_SHA,
                40, "text/plain", NOW));
        registry.insertVersionIfAbsent(new VersionRow(ARTICLE, VERSION, "제목", "발행처", "https://example.invalid/a",
                NOW.minusSeconds(3600), null, "datetime", null, TEXT, NOW.minusSeconds(60)));
        registry.movePointer(ARTICLE, null, VERSION);
        writeGrants(grant(GRANT, REVISION, PROVIDER, true, "known", List.of("read", "store", "model-send", "quote-display"),
                List.of("authored-replay"), List.of(SUMMARY, "document-sentiment", VERIFIER), null));
    }

    // ---- registry --------------------------------------------------------------------------------------------------------

    static String grant(String id, String revision, String source, boolean enabled, String rights, List<String> operations,
            List<String> recipients, List<String> purposes, String expiresAt) {
        ObjectNode node = StrictJson.newObject();
        node.put("grantId", id);
        node.put("revision", revision);
        node.put("sourceId", source);
        node.put("enabled", enabled);
        node.put("rights", rights);
        ArrayNode ops = node.putArray("allowedOperations");
        operations.forEach(ops::add);
        ArrayNode recs = node.putArray("recipients");
        recipients.forEach(recs::add);
        ArrayNode purs = node.putArray("purposes");
        purposes.forEach(purs::add);
        node.putArray("evidence").add("authored synthetic test");
        node.put("expiresAt", expiresAt);
        return node.toString();
    }

    static String defaultGrant() {
        return grant(GRANT, REVISION, PROVIDER, true, "known", List.of("read", "store", "model-send", "quote-display"),
                List.of("authored-replay"), List.of(SUMMARY, "document-sentiment", VERIFIER), null);
    }

    void writeGrants(String... grantsJson) throws IOException {
        Files.writeString(grants, "{\"schemaVersion\":\"zoop-ai-s1-1\",\"grants\":[" + String.join(",", grantsJson) + "]}");
    }

    // ---- ids and results -------------------------------------------------------------------------------------------------

    static String digest(String... pairs) {
        ObjectNode node = StrictJson.newObject();
        for (int i = 0; i < pairs.length; i += 2) {
            node.put(pairs[i], pairs[i + 1]);
        }
        return Canonical.digest(node);
    }

    static String evidenceIdOf(String analysisId) {
        return "ev-" + digest("analysisId", analysisId, "evidenceId", "e1");
    }

    static String artifactId(String job, String kind) {
        return "artifact-" + digest("jobId", job, "kind", kind, "inputDigest", INPUT_DIGEST);
    }

    static String resultJson(String analysisId, String artifactId, String resultVersion, Consumer<ObjectNode> edit) {
        ObjectNode node = StrictJson.newObject();
        node.put("schemaVersion", "zoop-ai-s1-1");
        node.put("artifactId", artifactId);
        node.put("documentId", ARTICLE);
        node.put("documentVersion", VERSION);
        node.put("resultVersion", resultVersion);
        node.put("text", "요약 본문");
        node.putArray("claims");
        ObjectNode citation = node.putArray("citations").addObject();
        citation.put("evidenceId", evidenceIdOf(analysisId));
        citation.put("documentId", ARTICLE);
        citation.put("documentVersion", VERSION);
        citation.put("textArtifactId", TEXT);
        citation.put("offsetUnit", "unicode_code_point");
        citation.put("start", START);
        citation.put("end", END);
        citation.put("quote", QUOTE);
        citation.put("inputKind", "body");
        citation.putArray("rawLocatorIds").add("loc-1");
        node.putArray("limitations").add("한계");
        node.put("producedAt", "2026-10-15T00:00:00Z");
        ObjectNode provenance = node.putObject("provenance");
        provenance.put("sourceKind", "synthetic");
        provenance.put("executionMode", "replay");
        provenance.put("recordingKind", "authored-test");
        edit.accept(node);
        return node.toString();
    }

    SummaryView summary(String id, String job, long requestNo, String status, String exactReceiptId, String resultVersion,
            String resultArtifactId, String semanticReceiptId, String resultJson) {
        return new SummaryView(id, ARTICLE, VERSION, "summary", null, status, requestNo, GRANT, REVISION, job, resultVersion,
                resultArtifactId, exactReceiptId, semanticReceiptId, resultJson);
    }

    EvidenceView evidenceRow(String id, String verificationArtifactId) {
        return new EvidenceView(id, ARTICLE, VERSION, TEXT, QUOTE, START, END, "body", Boolean.TRUE, verificationArtifactId);
    }

    void executions(String job, String owner, String grantId, String revision, Set<String> recipients) {
        for (String stage : List.of(SUMMARY, VERIFIER)) {
            read.executions.add(new InMemoryEvidenceRead.Execution(job, owner, grantId, revision, stage, recipients));
        }
    }

    // ---- the two worlds --------------------------------------------------------------------------------------------------

    /** Analysis {@code an-1} made its own calls under job {@code job-1}; returns the evidence id. */
    EvidenceWorld normal() {
        evidenceId = evidenceIdOf("an-1");
        read.evidence.put(evidenceId, evidenceRow(evidenceId, "exact-an-1"));
        read.summaries.add(summary("an-1", "job-1", 1, "available", "exact-an-1", "result-1", "artifact-main-1", "artifact-ver-1",
                resultJson("an-1", "artifact-main-1", "result-1", n -> { })));
        executions("job-1", "an-1", GRANT, REVISION, Set.of("authored-replay"));
        return this;
    }

    /**
     * Creator {@code an-0} (job {@code job-0}, withheld: it is only source-level context) made the calls; {@code an-2} (job
     * {@code job-2}) was served from the cache and has no execution of its own. Its exact receipt is a real file.
     */
    EvidenceWorld cached() throws IOException {
        return cached(n -> { });
    }

    EvidenceWorld cached(Consumer<ObjectNode> editReceipt) throws IOException {
        evidenceId = evidenceIdOf("an-2");
        read.evidence.put(evidenceId, evidenceRow(evidenceId, "exact-an-2"));
        read.summaries.add(summary("an-0", "job-0", 1, "withheld", null, null, null, null, null));
        read.addIdentity("job-0", new AnalysisIdentity("an-0", ARTICLE, VERSION, "summary", null));
        String main = artifactId("job-0", SUMMARY);
        String verifier = artifactId("job-0", VERIFIER);
        read.summaries.add(summary("an-2", "job-2", 2, "available", "exact-an-2", "result-2", main, verifier,
                resultJson("an-2", main, "result-2", n -> { })));
        executions("job-0", "an-0", GRANT, REVISION, Set.of("authored-replay"));
        writeReceipt("exact-an-2", receipt("an-2", "job-2", "job-0", "result-2", editReceipt));
        return this;
    }

    ObjectNode receipt(String analysisId, String aiJobId, String creatorJob, String resultVersion, Consumer<ObjectNode> edit) {
        ObjectNode node = StrictJson.newObject();
        node.put("schemaVersion", "zoop-exact-receipt-1");
        node.put("analysisId", analysisId);
        node.put("aiJobId", aiJobId);
        node.put("creatorJobId", creatorJob);
        node.put("kind", SUMMARY);
        node.put("documentId", ARTICLE);
        node.put("documentVersion", VERSION);
        node.put("textArtifactId", TEXT);
        node.put("textSha256", TEXT_SHA);
        node.put("inputDigest", INPUT_DIGEST);
        node.put("resultVersion", resultVersion);
        node.put("policyVersion", "zoop-document-gate-2");
        ObjectNode citation = node.putArray("citations").addObject();
        citation.put("evidenceId", evidenceIdOf(analysisId));
        citation.put("modelEvidenceId", "e1");
        citation.put("start", START);
        citation.put("end", END);
        citation.putArray("rawLocatorIds").add("loc-1");
        edit.accept(node);
        return node;
    }

    Path writeReceipt(String id, ObjectNode receipt) throws IOException {
        byte[] bytes = Canonical.bytes(receipt);
        try (ArtifactFileStore.Session session = store.open()) {
            ArtifactFileStore.StoredFile file = session.put("exact_receipt", id + ".json", bytes);
            registry.insertArtifactIfAbsent(new ArtifactRow(id, "exact_receipt", file.uri(), file.sha256(), file.bytes(),
                    "application/json", NOW));
        }
        return root.resolve("exact_receipt").resolve(id + ".json");
    }

    // ---- the service under test ------------------------------------------------------------------------------------------

    EvidenceService service() {
        return service(grants, store);
    }

    EvidenceService service(Path grantsPath, ArtifactFileStore artifactStore) {
        return new EvidenceService(read, registry, new DocumentReadGrants(grantsPath), new EvidenceArtifactReader(artifactStore),
                Clock.fixed(NOW, ZoneOffset.UTC), TransactionOperations.withoutTransaction());
    }

    static byte[] bytes(String text) {
        return text.getBytes(StandardCharsets.UTF_8);
    }
}
