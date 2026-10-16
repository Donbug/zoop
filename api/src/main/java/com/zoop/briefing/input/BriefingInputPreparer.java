package com.zoop.briefing.input;

import com.zoop.briefing.selection.BriefingCandidateSelector;
import com.zoop.briefing.selection.SelectionInput;
import java.io.IOException;
import java.nio.file.Files;
import java.time.Instant;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.core.StreamReadFeature;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** Freeze selection, provenance and optional EXACT AI request strings before lease acquisition. */
public final class BriefingInputPreparer {
    public static final String SCHEMA = "zoop-briefing-input-v1";
    public enum Availability { AVAILABLE, DELAYED, UNAVAILABLE }
    public record MarketObservation(String key, Availability status, String valueJson, Instant observedAt, String sourceRef) {
        public MarketObservation { Objects.requireNonNull(key); Objects.requireNonNull(status); }
    }
    /** Only the actual artifacts owner can register kind=briefing_input and return this receipt. */
    @FunctionalInterface public interface ArtifactRegistrar {
        Registration registerBriefingInput(FileBriefingInputStore.Staged staged) throws IOException;
    }
    public record Registration(String artifactId, String sha256, long bytes) {}
    public record Prepared(FileBriefingInputStore.Staged staged, BriefingCandidateSelector.Result selection) {}
    public record SourceSnapshot(String artifactId, String sha256, long bytes) {
        public SourceSnapshot {
            if (artifactId == null || artifactId.isBlank() || sha256 == null || !sha256.matches("[0-9a-f]{64}") || bytes < 0)
                throw new IllegalArgumentException("Actual source snapshot identity required");
        }
    }

    private final FileBriefingInputStore store;
    private final JsonMapper mapper = JsonMapper.builder()
        .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
        .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
        .enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS).build();
    private final BriefingCandidateSelector selector = new BriefingCandidateSelector();

    public BriefingInputPreparer(FileBriefingInputStore store) { this.store = Objects.requireNonNull(store); }

    public Prepared prepare(SelectionInput input, List<MarketObservation> market,
            Map<String, String> exactAiRequests) throws IOException {
        return prepare(input, market, exactAiRequests, null);
    }

    public Prepared prepare(SelectionInput input, List<MarketObservation> market,
            Map<String, String> exactAiRequests, SourceSnapshot sourceSnapshot) throws IOException {
        var selected = selector.select(input); // Query failure must not freeze a successful empty round.
        var root = mapper.createObjectNode().put("schema", SCHEMA);
        JsonNode inputTree = mapper.valueToTree(input);
        normalizeInput((ObjectNode) inputTree);
        root.set("input", inputTree);
        root.set("selection", mapper.valueToTree(selected));
        if (sourceSnapshot != null) root.set("sourceSnapshot", mapper.valueToTree(sourceSnapshot));
        var observations = root.putArray("marketObservations");
        var keys = new HashSet<String>();
        market.stream().sorted(Comparator.comparing(MarketObservation::key)).forEach(o -> {
            if (o.key().isBlank() || !keys.add(o.key())) throw new IllegalArgumentException("Duplicate/blank market key");
            if (o.observedAt() != null && o.observedAt().isAfter(input.context().scheduledAt()))
                throw new IllegalArgumentException("Future market observation");
            if ((o.status() == Availability.AVAILABLE || o.valueJson() != null) && (o.valueJson() == null || o.observedAt() == null
                    || o.sourceRef() == null || o.sourceRef().isBlank()))
                throw new IllegalArgumentException("Available observation needs value/time/source");
            if (o.status() == Availability.UNAVAILABLE && o.valueJson() != null)
                throw new IllegalArgumentException("Unavailable observation cannot contain a fabricated value");
            var node = observations.addObject().put("key", o.key()).put("status", o.status().name());
            node.set("value", o.valueJson() == null ? mapper.nullNode() : json(o.valueJson()));
            if (o.observedAt() == null) node.putNull("observedAt"); else node.put("observedAt", o.observedAt().toString());
            if (o.sourceRef() == null) node.putNull("sourceRef"); else node.put("sourceRef", o.sourceRef());
        });
        var requests = root.putObject("exactAiRequests");
        exactAiRequests.forEach((key, raw) -> {
            if (key.isBlank() || !json(raw).isObject()) throw new IllegalArgumentException("Named exact JSON object required");
            requests.put(key, raw); // Preserve whitespace/ordering/escapes in the actual transport body.
        });
        byte[] bytes = mapper.writeValueAsBytes(canonical(root));
        return new Prepared(store.put(bytes), selected);
    }

    /** Attach an already prefetched private bundle without inventing a timestamp for daily closes. */
    public Prepared prepareWithMarketSnapshot(SelectionInput input, com.zoop.briefing.market.MarketSnapshot market,
            Map<String,String> exactAiRequests, SourceSnapshot sourceSnapshot) throws IOException {
        var restored=com.zoop.briefing.market.MarketSnapshot.restore(Objects.requireNonNull(market).staged());
        var bundle=restored.json(); var context=bundle.path("runContext"); var expected=input.context();
        if(!context.path("roundId").asString().equals(expected.roundId())
                ||!context.path("edition").asString().equals(expected.edition())
                ||!Instant.parse(context.path("sourceCutoff").asString()).equals(expected.scheduledAt())
                ||context.path("firstRound").asBoolean()!=expected.firstRound()
                ||(expected.from()==null?!context.path("windowFrom").isNull():!expected.from().toString().equals(context.path("windowFrom").asString()))
                ||Instant.parse(bundle.path("inputFrozenAt").asString()).isAfter(expected.scheduledAt()))
            throw new IllegalArgumentException("Market snapshot belongs to a different round/window");
        var prepared=prepare(input,List.of(),exactAiRequests,sourceSnapshot);
        var root=(ObjectNode)mapper.readTree(Files.readAllBytes(prepared.staged().path()));
        root.set("marketSnapshot",bundle);
        root.putObject("marketSnapshotRef").put("sha256",restored.staged().sha256()).put("bytes",restored.staged().bytes());
        // Keep full 4-state indicators in the separate bundle; old 3-state observations remain unchanged.
        return new Prepared(store.put(mapper.writeValueAsBytes(canonical(root))),prepared.selection());
    }

    /** No default registrar, fake registry or implicit lease acquisition. Registration must finish first. */
    public Registration register(Prepared prepared, ArtifactRegistrar registrar) throws IOException {
        var staged = prepared.staged();
        if (Files.isSymbolicLink(staged.path()) || !Files.isRegularFile(staged.path(), java.nio.file.LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Staged input must be a regular private file");
        byte[] bytes = Files.readAllBytes(staged.path());
        if (bytes.length != staged.bytes() || !FileBriefingInputStore.sha256(bytes).equals(staged.sha256()))
            throw new IOException("Staged input changed before registration");
        var receipt = Objects.requireNonNull(registrar).registerBriefingInput(staged);
        if (receipt == null || receipt.artifactId() == null || receipt.artifactId().isBlank()
                || !staged.sha256().equals(receipt.sha256()) || receipt.bytes() != staged.bytes())
            throw new IOException("Artifact registration receipt does not match frozen bytes");
        return receipt;
    }

    private JsonNode json(String raw) {
        try {
            JsonNode parsed = mapper.readTree(raw);
            if (parsed == null || parsed.isMissingNode() || parsed.isNull()) throw new IllegalArgumentException("JSON value required");
            return parsed;
        } catch (tools.jackson.core.JacksonException e) { throw new IllegalArgumentException("Invalid JSON"); }
    }

    private void normalizeInput(ObjectNode input) {
        sortObjects((ArrayNode) input.path("candidates"), "eventId");
        for (var candidate : input.path("candidates")) {
            sortStrings((ArrayNode) candidate.path("factEvidenceIds"));
            var impact = candidate.path("impact");
            sortStrings((ArrayNode) impact.path("evidenceIds"));
            sortObjects((ArrayNode) impact.path("sectorEffects"), "sectorId");
            for (var effect : impact.path("sectorEffects")) sortStrings((ArrayNode) effect.path("evidenceIds"));
            sortObjects((ArrayNode) candidate.path("evidence"), "id");
            for (var evidence : candidate.path("evidence")) {
                var grant = evidence.path("checkedScope");
                for (String field : List.of("requiredOperations", "requiredPurposes", "requiredRecipients"))
                    sortStrings((ArrayNode) grant.path(field));
            }
        }
    }
    private void sortObjects(ArrayNode array, String field) {
        var list = new ArrayList<JsonNode>(); array.forEach(list::add);
        list.sort((a, b) -> BriefingCandidateSelector.compareCodePoints(a.path(field).asString(), b.path(field).asString()));
        array.removeAll(); list.forEach(array::add);
    }
    private void sortStrings(ArrayNode array) {
        var strings = new TreeSet<String>(BriefingCandidateSelector::compareCodePoints);
        array.forEach(n -> strings.add(n.asString())); array.removeAll(); strings.forEach(array::add);
    }
    private JsonNode canonical(JsonNode node) {
        if (node.isObject()) {
            var result = mapper.createObjectNode();
            node.propertyNames().stream().sorted(BriefingCandidateSelector::compareCodePoints)
                .forEach(key -> result.set(key, canonical(node.path(key))));
            return result;
        }
        if (node.isArray()) { var result = mapper.createArrayNode(); node.forEach(n -> result.add(canonical(n))); return result; }
        return node;
    }
}
