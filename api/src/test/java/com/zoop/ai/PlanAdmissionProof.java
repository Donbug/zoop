package com.zoop.ai;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.function.Predicate;
import java.util.function.Supplier;

import com.zoop.ai.http.HttpExtractionClient;
import com.zoop.ai.http.HttpPlanAdmissionClient;
import com.zoop.ai.http.HttpRelationClient;
import com.zoop.ai.plan.PlanAdmission;
import com.zoop.ai.plan.PlanManifest;
import com.zoop.ai.plan.PlanReference;
import tools.jackson.core.StreamReadFeature;
import tools.jackson.core.json.JsonFactory;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Test-only runner over private synthetic inputs. Never writes policy, source rights, reviews, publication or app state. */
public final class PlanAdmissionProof {
    private static final JsonMapper JSON = JsonMapper.builder(JsonFactory.builder().build())
            .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION).enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
            .enable(tools.jackson.databind.SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).build();

    private PlanAdmissionProof() {
    }

    public static void main(String[] args) {
        try {
            run(args);
        } catch (Exception error) {
            // No exception text, child output, input JSON, paths or credentials in process output.
            String code = error instanceof AiServiceRejectionException rejection ? rejection.code()
                    : error instanceof AiTransportException transport ? transport.failure().name() : error.getClass().getSimpleName();
            System.err.println("plan-admission-proof failed: " + code);
            System.exit(1);
        }
    }

    private static void run(String[] args) throws Exception {
        require(args.length == 3);
        JsonNode config = read(Path.of(args[0]), Set.of("baseUrl", "token"));
        JsonNode input = read(Path.of(args[1]), Set.of("schemaVersion", "planId", "planDigest"));
        require(PlanReference.SCHEMA_VERSION.equals(text(input, "schemaVersion")));
        PlanReference reference = new PlanReference(text(input, "planId"), text(input, "planDigest"));
        Path evidence = Path.of(args[2]);
        Files.createDirectories(evidence);
        require(Files.isDirectory(evidence, LinkOption.NOFOLLOW_LINKS));
        // Persist the exact stable reference before the first outbound action, including admission itself.
        persist(evidence.resolve("reference.json"), JSON.writeValueAsBytes(Map.of("schemaVersion", PlanReference.SCHEMA_VERSION,
                "planId", reference.planId(), "planDigest", reference.planDigest())));
        AiClientSettings settings = AiClientSettings.of(text(config, "baseUrl"), text(config, "token"), Duration.ofSeconds(3), Duration.ofSeconds(60), 16_000_000);
        try (var plans = new HttpPlanAdmissionClient(settings); var extraction = new HttpExtractionClient(settings); var relation = new HttpRelationClient(settings)) {
            PlanAdmission admitted = reconcile(() -> plans.admit(reference), () -> plans.status(reference));
            PlanAdmission observed = plans.status(reference);
            require(admitted.equals(observed));
            require(observed.authority().state() == PlanAdmission.State.ACTIVE);
            require(observed.manifest().provenance().sourceKind() == PipelineJob.SourceKind.SYNTHETIC);
            require(observed.manifest().provenance().executionMode() == ExecutionMode.REPLAY);
            var identities = new ArrayList<Map<String, String>>();
            for (PlanManifest.Unit unit : observed.manifest().units()) {
                identities.add(Map.of("unitKey", unit.unitKey(), "approvedRequestDigest", unit.extractionSubmit().approvedRequestDigest(),
                        "extractionInputDigest", unit.extractionInputDigest(), "relationJobId", unit.relationSubmit().jobId()));
            }
            persist(evidence.resolve("unit-identities.json"), JSON.writeValueAsBytes(Map.of("admissionId", observed.admissionId(),
                    "manifestDigest", observed.manifest().manifestDigest(), "units", identities)));
            var outcomes = new ArrayList<Map<String, Object>>();
            long providerCalls = 0;
            for (PlanManifest.Unit unit : observed.manifest().units()) {
                // The policy check is necessary but not sufficient: existing clients/service enforce current use/source gates.
                require(plans.status(reference).authority().state() == PlanAdmission.State.ACTIVE);
                var s2ack = reconcile(() -> extraction.submit(unit.extractionSubmit()).disposition().name(),
                        () -> { extraction.status(unit.unitKey()); return "RECONCILED_BY_STATUS"; });
                var s2 = poll(() -> extraction.status(unit.unitKey()), status -> status.state() == PipelineJob.State.READY
                        && status.dispatch().state() == PipelineJob.DispatchState.IDLE);
                require(s2.sourceKind() == PipelineJob.SourceKind.SYNTHETIC && s2.executionMode() == ExecutionMode.REPLAY);
                require(s2.approvedRequestDigest().equals(unit.extractionSubmit().approvedRequestDigest()));
                require(s2.inputDigest().equals(unit.extractionInputDigest()));
                require(s2.usage().providerCalls() == 0 && s2.usage().paidModelCalls() == 0 && s2.usage().startedWithoutReceipt() == 0);
                var s2result = extraction.result(unit.unitKey());
                require(s2result.delivery().state() == PipelineJob.DeliveryState.AVAILABLE);
                var consumedS2 = s2result.status();
                require(consumedS2.approvedRequestDigest().equals(unit.extractionSubmit().approvedRequestDigest()));
                require(consumedS2.inputDigest().equals(unit.extractionInputDigest()));
                require(consumedS2.sourceKind() == observed.manifest().provenance().sourceKind()
                        && consumedS2.executionMode() == observed.manifest().provenance().executionMode());
                require(consumedS2.usage().providerCalls() == 0 && consumedS2.usage().paidModelCalls() == 0
                        && consumedS2.usage().startedWithoutReceipt() == 0);
                JsonNode s2payload = JSON.readTree(s2result.readyPayload().orElseThrow().untrustedJson());
                JsonNode events = s2payload.get("eventCandidates");
                require(events != null && events.isArray());
                for (JsonNode event : events.values()) {
                    require(event.get("approved") != null && event.get("approved").isBoolean() && !event.get("approved").booleanValue());
                }
                require(plans.status(reference).authority().state() == PlanAdmission.State.ACTIVE);
                var s3ack = reconcile(() -> relation.submit(unit.relationSubmit()).disposition().name(),
                        () -> { relation.status(unit.relationSubmit().jobId()); return "RECONCILED_BY_STATUS"; });
                var s3 = poll(() -> relation.status(unit.relationSubmit().jobId()), status -> status.state() == PipelineJob.State.READY
                        && status.dispatch().state() == PipelineJob.DispatchState.IDLE);
                require(s3.sourceKind() == PipelineJob.SourceKind.SYNTHETIC && s3.executionMode() == ExecutionMode.REPLAY);
                require(s3.upstream().equals(unit.relationSubmit().upstream()));
                require(s3.usage().providerCalls() == 0 && s3.usage().modelCalls() == 0 && s3.usage().startedWithoutReceipt() == 0);
                var s3result = relation.result(unit.relationSubmit().jobId());
                require(s3result.delivery().state() == PipelineJob.DeliveryState.AVAILABLE);
                var consumedS3 = s3result.status();
                require(consumedS3.upstream().equals(unit.relationSubmit().upstream()));
                require(consumedS3.inputDigest().equals(s3.inputDigest()));
                require(consumedS3.sourceKind() == observed.manifest().provenance().sourceKind()
                        && consumedS3.executionMode() == observed.manifest().provenance().executionMode());
                require(consumedS3.usage().providerCalls() == 0 && consumedS3.usage().modelCalls() == 0
                        && consumedS3.usage().startedWithoutReceipt() == 0);
                var payload = s3result.readyPayload().orElseThrow();
                var outcome = new LinkedHashMap<String, Object>();
                outcome.put("unitKey", unit.unitKey());
                outcome.put("extractionJobId", consumedS2.jobId());
                outcome.put("extractionInputDigest", consumedS2.inputDigest());
                outcome.put("relationJobId", consumedS3.jobId());
                outcome.put("s2Disposition", s2ack);
                outcome.put("s3Disposition", s3ack);
                outcome.put("s2ProviderCalls", consumedS2.usage().providerCalls());
                outcome.put("s3ProviderCalls", consumedS3.usage().providerCalls());
                outcome.put("s2DispatchCount", consumedS2.dispatch().dispatchCount());
                outcome.put("s3DispatchCount", consumedS3.dispatch().dispatchCount());
                providerCalls = Math.addExact(providerCalls, Math.addExact(consumedS2.usage().providerCalls(), consumedS3.usage().providerCalls()));
                outcome.put("s2EventCandidates", events.size());
                outcome.put("s3Candidates", payload.candidates().size());
                outcomes.add(outcome);
            }
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("planId", reference.planId());
            result.put("planDigest", reference.planDigest());
            result.put("admissionId", observed.admissionId());
            result.put("manifestDigest", observed.manifest().manifestDigest());
            result.put("authority", "active");
            result.put("units", outcomes);
            result.put("providerCalls", providerCalls);
            persist(evidence.resolve("result.json"), JSON.writeValueAsBytes(result));
        }
    }

    private static <T> T reconcile(Supplier<T> mutation, Supplier<T> status) {
        try {
            return mutation.get();
        } catch (AiClientException error) {
            if (!error.requestMaybeProcessed()) {
                throw error;
            }
            // Exactly the same identity. If still unknown, fail: no replacement ID and no hidden submit retry.
            return status.get();
        }
    }

    private static <T> T poll(Supplier<T> read, Predicate<T> ready) throws InterruptedException {
        long deadline = System.nanoTime() + Duration.ofSeconds(120).toNanos();
        do {
            T value = read.get();
            if (ready.test(value)) {
                return value;
            }
            Thread.sleep(100);
        } while (System.nanoTime() < deadline);
        throw new IllegalStateException("synthetic pipeline did not become ready");
    }

    private static JsonNode read(Path path, Set<String> keys) throws IOException {
        require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) && Files.size(path) <= 65_536);
        JsonNode node = JSON.readTree(Files.readAllBytes(path));
        require(node != null && node.isObject() && node.size() == keys.size()
                && node.properties().stream().allMatch(entry -> keys.contains(entry.getKey())));
        return node;
    }

    private static String text(JsonNode node, String key) {
        JsonNode value = node.get(key);
        require(value != null && value.isString());
        return value.stringValue();
    }

    /** Fsync staging then no-clobber publish: a killed process cannot publish partial stable identities. */
    private static void persist(Path target, byte[] bytes) throws IOException {
        if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) {
            require(Files.isRegularFile(target, LinkOption.NOFOLLOW_LINKS) && java.util.Arrays.equals(bytes, Files.readAllBytes(target)));
            return;
        }
        Path staging = Files.createTempFile(target.getParent(), ".proof-", ".tmp");
        try {
            try (FileChannel channel = FileChannel.open(staging, StandardOpenOption.WRITE)) {
                ByteBuffer buffer = ByteBuffer.wrap(bytes);
                while (buffer.hasRemaining()) {
                    channel.write(buffer);
                }
                channel.force(true);
            }
            try {
                Files.createLink(target, staging);
            } catch (FileAlreadyExistsException race) {
                require(Files.isRegularFile(target, LinkOption.NOFOLLOW_LINKS) && java.util.Arrays.equals(bytes, Files.readAllBytes(target)));
            }
            try (FileChannel directory = FileChannel.open(target.getParent(), StandardOpenOption.READ)) {
                directory.force(true);
            }
        } finally {
            Files.deleteIfExists(staging);
        }
    }

    private static void require(boolean condition) {
        if (!condition) {
            throw new IllegalStateException("synthetic proof contract violation");
        }
    }
}
