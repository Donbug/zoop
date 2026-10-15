package com.zoop.document.analysis;

import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;

/**
 * Read-side proof of who created the artifacts of a settled summary. A result served from the artifact cache records its
 * calls under the CREATING job, and nothing in SQL links the cache-served analysis to that job: the only stored link is
 * {@code creatorJobId} in the analysis's own exact receipt file, which also carries the {@code inputDigest} that the
 * content-addressed artifact ids are built from. This class checks the receipt, given as the bytes of a file the caller has
 * already verified against the registry's hash and size, against everything SQL says about the analysis, and returns the
 * creator job only when all of it agrees. It reads nothing itself and never throws: any doubt is {@code null}.
 */
public final class ExactReceiptProof {
    private static final Set<String> KEYS = Set.of("schemaVersion", "analysisId", "aiJobId", "creatorJobId", "kind",
            "documentId", "documentVersion", "textArtifactId", "textSha256", "inputDigest", "resultVersion", "policyVersion",
            "citations");
    private static final Set<String> CITATION_KEYS = Set.of("evidenceId", "modelEvidenceId", "start", "end", "rawLocatorIds");
    private static final Pattern JOB_ID = Pattern.compile("[A-Za-z0-9_.-]{1,120}");
    private static final String SUMMARY = "document-summary";
    private static final String VERIFIER = "semantic-verification";

    private ExactReceiptProof() {
    }

    /**
     * What SQL and the registry say about the analysis and the cited evidence.
     *
     * @param analysisId        {@code document_analyses.id}
     * @param aiJobId           {@code document_analyses.ai_job_id}
     * @param articleId         the analysed article
     * @param articleVersion    the analysed version
     * @param textArtifactId    the stored text artifact the evidence cites
     * @param textSha256        {@code artifacts.sha256} of that text artifact
     * @param resultVersion     {@code document_analyses.result_version}
     * @param resultArtifactId  {@code document_analyses.result_artifact_id}
     * @param semanticReceiptId {@code document_analyses.semantic_receipt_id}
     * @param evidenceId        the evidence being read
     * @param start             its start offset (Unicode code points)
     * @param end               its end offset, exclusive
     */
    public record Subject(String analysisId, String aiJobId, String articleId, String articleVersion, String textArtifactId,
            String textSha256, String resultVersion, String resultArtifactId, String semanticReceiptId, String evidenceId,
            long start, long end) {
    }

    /** The creator job of the artifacts, or {@code null} when the receipt does not prove exactly this analysis and evidence. */
    public static String creatorJobId(byte[] receipt, Subject subject) {
        try {
            StrictJson.Obj root = StrictJson.parseObject(receipt).exactly(KEYS);
            String creator = root.string("creatorJobId");
            String inputDigest = root.string("inputDigest");
            if (!ResultAssessor.EXACT_SCHEMA.equals(root.string("schemaVersion"))
                    || !subject.analysisId().equals(root.string("analysisId"))
                    || !subject.aiJobId().equals(root.string("aiJobId"))
                    || !SUMMARY.equals(root.string("kind"))
                    || !subject.articleId().equals(root.string("documentId"))
                    || !subject.articleVersion().equals(root.string("documentVersion"))
                    || !subject.textArtifactId().equals(root.string("textArtifactId"))
                    || !subject.textSha256().equals(root.string("textSha256"))
                    || !subject.resultVersion().equals(root.string("resultVersion"))
                    || !ResultAssessor.POLICY_VERSION.equals(root.string("policyVersion"))
                    || !JOB_ID.matcher(creator).matches() || creator.equals(subject.aiJobId())
                    || !StrictJson.SHA256.matcher(inputDigest).matches()
                    || !subject.resultArtifactId().equals(ResultAssessor.artifactId(creator, SUMMARY, inputDigest))
                    || !subject.semanticReceiptId().equals(ResultAssessor.artifactId(creator, VERIFIER, inputDigest))
                    || !cites(root, subject)) {
                return null;
            }
            return creator;
        } catch (StrictJson.Malformed malformed) {
            return null;
        }
    }

    /** Exactly one citation carries the evidence id, derives it from the analysis, and has the evidence's offsets. */
    private static boolean cites(StrictJson.Obj root, Subject subject) {
        int matches = 0;
        for (JsonNode node : root.array("citations").values()) {
            StrictJson.Obj citation = StrictJson.Obj.of(node).exactly(CITATION_KEYS);
            citation.array("rawLocatorIds");
            String evidenceId = citation.stringOrNull("evidenceId");
            if (!subject.evidenceId().equals(evidenceId)) {
                continue;
            }
            matches++;
            if (!subject.evidenceId().equals(ResultAssessor.evidenceId(subject.analysisId(), citation.string("modelEvidenceId")))
                    || citation.count("start") != subject.start() || citation.count("end") != subject.end()) {
                return false;
            }
        }
        return matches == 1;
    }
}
