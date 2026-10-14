package com.zoop.document.analysis;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AnalysisKind;
import com.zoop.ai.AnalysisSubmission;
import com.zoop.ai.ExecutionMode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.Text;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * The immutable AI {@code Submit} of one analysis ({@code docs/api/ai-contract.schema.json}), exactly as it is stored in the
 * {@code ai_submit} artifact and later sent: the document as the S2-1 export delivered it, the operator-declared company
 * (id and the catalog's name, frozen), the grant reference and the provenance. Its canonical bytes (Python
 * {@code json.dumps(sort_keys)} form) are the artifact, and everything the app later checks a result against is read from
 * them, never from the AI service.
 *
 * <p>Parsing is strict and closed: any unknown or missing key, any wrong type or any value outside the contract is
 * {@link StrictJson.Malformed}. {@link #parse} additionally requires that the bytes are already canonical.
 */
public final class AnalysisSubmit {
    private static final Set<String> TOP = Set.of("schemaVersion", "jobId", "kind", "input", "mode", "provenance");
    private static final Set<String> INPUT = Set.of("document", "company", "grantId", "grantRevision", "candidate");
    private static final Set<String> DOCUMENT = Set.of("documentId", "documentVersion", "sourceId", "textArtifactId", "inputKind",
            "cleanerVersion", "text", "sourceHash", "rawLocators");
    private static final Set<String> PROVENANCE = Set.of("sourceKind", "executionMode", "recordingKind");

    /** A span of the document text (code points, end exclusive) that the source can be traced back to. */
    public record RawLocator(String id, int start, int end) {
    }

    private final ObjectNode root;
    private final String jobId;
    private final AnalysisKind kind;
    private final ExecutionMode mode;
    private final String sourceKind;
    private final String documentId;
    private final String documentVersion;
    private final String sourceId;
    private final String textArtifactId;
    private final String text;
    private final List<RawLocator> locators;
    private final String companyId;
    private final String companyName;
    private final String grantId;
    private final String grantRevision;

    private AnalysisSubmit(ObjectNode root, String jobId, AnalysisKind kind, ExecutionMode mode, String sourceKind,
            String documentId, String documentVersion, String sourceId, String textArtifactId, String text,
            List<RawLocator> locators, String companyId, String companyName, String grantId, String grantRevision) {
        this.root = root;
        this.jobId = jobId;
        this.kind = kind;
        this.mode = mode;
        this.sourceKind = sourceKind;
        this.documentId = documentId;
        this.documentVersion = documentVersion;
        this.sourceId = sourceId;
        this.textArtifactId = textArtifactId;
        this.text = text;
        this.locators = List.copyOf(locators);
        this.companyId = companyId;
        this.companyName = companyName;
        this.grantId = grantId;
        this.grantRevision = grantRevision;
    }

    /**
     * Builds the submit of a new analysis from the validated S2-1 {@code document}. {@code sourceKind} is the operator's
     * statement whether the text is synthetic or actual; the execution and recording kinds follow from the mode.
     */
    public static AnalysisSubmit build(String jobId, AnalysisKind kind, ExecutionMode mode, String sourceKind, JsonNode document,
            String companyId, String companyName, String grantId, String grantRevision) {
        ObjectNode submit = StrictJson.newObject();
        submit.put("schemaVersion", AnalysisSubmission.SCHEMA_VERSION);
        submit.put("jobId", jobId);
        submit.put("kind", kind.wire());
        submit.put("mode", mode.wire());
        ObjectNode input = submit.putObject("input");
        input.set("document", document.deepCopy());
        ObjectNode company = input.putObject("company");
        company.put("companyId", companyId);
        company.put("name", companyName);
        input.put("grantId", grantId);
        input.put("grantRevision", grantRevision);
        input.putNull("candidate");
        ObjectNode provenance = submit.putObject("provenance");
        provenance.put("sourceKind", sourceKind);
        provenance.put("executionMode", mode.wire());
        provenance.put("recordingKind", mode == ExecutionMode.REPLAY ? "authored-test" : "provider");
        return validate(submit);
    }

    /** The stored artifact: strict UTF-8 canonical JSON of a valid submit; anything else is {@link StrictJson.Malformed}. */
    public static AnalysisSubmit parse(byte[] bytes) {
        StrictJson.Obj parsed = StrictJson.parseObject(bytes);
        AnalysisSubmit submit = validate(parsed.node());
        if (!java.util.Arrays.equals(submit.bytes(), bytes)) {
            throw new StrictJson.Malformed();
        }
        return submit;
    }

    private static AnalysisSubmit validate(JsonNode node) {
        StrictJson.Obj top = StrictJson.Obj.of(node).exactly(TOP);
        if (!AnalysisSubmission.SCHEMA_VERSION.equals(top.string("schemaVersion"))) {
            throw new StrictJson.Malformed();
        }
        String jobId = top.string("jobId");
        if (!AnalysisSubmission.JOB_ID.matcher(jobId).matches()) {
            throw new StrictJson.Malformed();
        }
        AnalysisKind kind = AnalysisKind.fromWire(top.string("kind")).orElseThrow(StrictJson.Malformed::new);
        if (kind != AnalysisKind.DOCUMENT_SUMMARY && kind != AnalysisKind.DOCUMENT_SENTIMENT) {
            throw new StrictJson.Malformed();
        }
        ExecutionMode mode = ExecutionMode.fromWire(top.string("mode")).orElseThrow(StrictJson.Malformed::new);

        StrictJson.Obj provenance = top.object("provenance").exactly(PROVENANCE);
        String sourceKind = provenance.string("sourceKind");
        if (!sourceKind.equals("synthetic") && !sourceKind.equals("actual")) {
            throw new StrictJson.Malformed();
        }
        String recording = mode == ExecutionMode.REPLAY ? "authored-test" : "provider";
        if (!mode.wire().equals(provenance.string("executionMode")) || !recording.equals(provenance.string("recordingKind"))
                || (mode == ExecutionMode.REPLAY && !sourceKind.equals("synthetic"))) {
            throw new StrictJson.Malformed();
        }

        StrictJson.Obj input = top.object("input").exactly(INPUT);
        if (!input.isNull("candidate")) {
            throw new StrictJson.Malformed();
        }
        StrictJson.Obj document = input.object("document").exactly(DOCUMENT);
        String documentId = nonEmpty(document.string("documentId"));
        String documentVersion = nonEmpty(document.string("documentVersion"));
        String sourceId = nonEmpty(document.string("sourceId"));
        String textArtifactId = nonEmpty(document.string("textArtifactId"));
        nonEmpty(document.string("cleanerVersion"));
        if (!"body".equals(document.string("inputKind"))) {
            throw new StrictJson.Malformed();
        }
        String text = nonEmpty(document.string("text"));
        if (Text.strictUtf8(text) == null
                || !document.string("sourceHash").equals(Canonical.sha256(Text.pythonJsonString(text)))) {
            throw new StrictJson.Malformed();
        }
        int codePoints = Text.codePoints(text);
        List<RawLocator> locators = new ArrayList<>();
        Set<String> locatorIds = new HashSet<>();
        for (StrictJson.Obj locator : document.objects("rawLocators")) {
            locator.exactly(Set.of("locatorId", "start", "end"));
            RawLocator parsed = new RawLocator(nonEmpty(locator.string("locatorId")), locator.count("start"), locator.count("end"));
            if (parsed.start() >= parsed.end() || parsed.end() > codePoints || !locatorIds.add(parsed.id())) {
                throw new StrictJson.Malformed();
            }
            locators.add(parsed);
        }
        if (locators.isEmpty()) {
            throw new StrictJson.Malformed();
        }
        StrictJson.Obj company = input.object("company").exactly(Set.of("companyId", "name"));
        return new AnalysisSubmit((ObjectNode) node, jobId, kind, mode, sourceKind, documentId, documentVersion, sourceId,
                textArtifactId, text, locators, nonEmpty(company.string("companyId")), nonEmpty(company.string("name")),
                nonEmpty(input.string("grantId")), nonEmpty(input.string("grantRevision")));
    }

    private static String nonEmpty(String value) {
        if (value.isEmpty()) {
            throw new StrictJson.Malformed();
        }
        return value;
    }

    /** The canonical bytes: the {@code ai_submit} artifact content. */
    public byte[] bytes() {
        return Canonical.bytes(root);
    }

    public boolean withinRequestLimit() {
        return bytes().length <= AiClientSettings.MAX_REQUEST_BYTES;
    }

    /** The submit with its job id removed, canonical: two analyses ask the model the same thing exactly when these are equal. */
    public String identity() {
        ObjectNode copy = (ObjectNode) root.deepCopy();
        copy.remove("jobId");
        return Canonical.write(copy);
    }

    /** The canonical text of the submit as the AI service echoes it in a result ({@code job.input}). */
    public String canonicalText() {
        return Canonical.write(root);
    }

    public AnalysisSubmission toSubmission() {
        return new AnalysisSubmission(jobId, kind, mode, Canonical.write(root.get("input")), Canonical.write(root.get("provenance")));
    }

    public JsonNode documentNode() {
        return root.get("input").get("document");
    }

    public JsonNode provenanceNode() {
        return root.get("provenance");
    }

    public String jobId() {
        return jobId;
    }

    public AnalysisKind kind() {
        return kind;
    }

    public ExecutionMode mode() {
        return mode;
    }

    public String sourceKind() {
        return sourceKind;
    }

    public String documentId() {
        return documentId;
    }

    public String documentVersion() {
        return documentVersion;
    }

    public String sourceId() {
        return sourceId;
    }

    public String textArtifactId() {
        return textArtifactId;
    }

    public String text() {
        return text;
    }

    public List<RawLocator> locators() {
        return locators;
    }

    public String companyId() {
        return companyId;
    }

    public String companyName() {
        return companyName;
    }

    public String grantId() {
        return grantId;
    }

    public String grantRevision() {
        return grantRevision;
    }

    /** The content is never printed. */
    @Override
    public String toString() {
        return "AnalysisSubmit[jobId=" + jobId + ", kind=" + kind.wire() + ", mode=" + mode.wire() + "]";
    }
}
