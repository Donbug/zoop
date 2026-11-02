package com.zoop.graph.importer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.Text;
import com.zoop.document.importer.Observation;
import com.zoop.graph.importer.HandoffBundle.SourcePin;

/** Private operator-pinned native routes shared by the handoff CLI and actual ingestion exports. */
public final class HandoffSourceContexts {
    public static final String SCHEMA = "zoop-handoff-source-contexts-1";
    private static final int MAX_BYTES = 2_000_000;
    private static final Pattern ID = Pattern.compile("[A-Za-z0-9._:-]{1,200}");
    private static final Set<String> CONTEXT = Set.of("contextId", "relationStateDirectory", "extractionStateDirectory",
            "ingestionStateDirectory", "sources", "sourcePins", "observations");
    private static final Set<String> OBSERVATION = Set.of("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion");
    public record Context(String id, Path relation, Path extraction, Path ingestion, Path sources) {}
    private final Path file;
    private final String sha256;
    private final List<Context> contexts;
    private final Map<SourcePin, Context> pins;
    private final Map<Observation, Context> observations;

    private HandoffSourceContexts(Path file, String sha256, List<Context> contexts, Map<SourcePin, Context> pins,
            Map<Observation, Context> observations) {
        this.file = file;
        this.sha256 = sha256;
        this.contexts = List.copyOf(contexts);
        this.pins = Map.copyOf(pins);
        this.observations = Map.copyOf(observations);
    }

    public static HandoffSourceContexts read(Path file, String sha256) {
        try {
            if (sha256 == null || !StrictJson.SHA256.matcher(sha256).matches()) throw new StrictJson.Malformed();
            byte[] raw = readBytes(file);
            if (!Canonical.sha256(raw).equals(sha256)) throw new StrictJson.Malformed();
            var root = StrictJson.parseObject(raw).exactly(Set.of("schemaVersion", "contexts"));
            if (!SCHEMA.equals(root.string("schemaVersion"))) throw new StrictJson.Malformed();
            List<Context> contexts = new ArrayList<>();
            Map<SourcePin, Context> pins = new HashMap<>();
            Map<Observation, Context> observations = new HashMap<>();
            Set<String> ids = new HashSet<>();
            Map<String, List<String>> jobs = new HashMap<>();
            Map<String, List<String>> upstreams = new HashMap<>();
            for (var entry : root.objects("contexts")) {
                entry.exactly(CONTEXT);
                Context context = new Context(text(entry, "contextId"), path(entry, "relationStateDirectory"),
                        path(entry, "extractionStateDirectory"), path(entry, "ingestionStateDirectory"), path(entry, "sources"));
                if (!ids.add(context.id())) throw new StrictJson.Malformed();
                contexts.add(context);
                var sourcePins = entry.objects("sourcePins");
                var refs = entry.objects("observations");
                if (sourcePins.isEmpty() || refs.isEmpty()) throw new StrictJson.Malformed();
                for (var item : sourcePins) {
                    item.exactly(Set.of("relation", "upstream", "reviewDigest"));
                    var relation = item.object("relation").exactly(Set.of("jobId", "inputDigest"));
                    var upstream = item.object("upstream").exactly(Set.of("jobId", "inputDigest", "digest"));
                    SourcePin pin = new SourcePin(job(relation), hash(relation, "inputDigest"), job(upstream),
                            hash(upstream, "inputDigest"), hash(upstream, "digest"), hash(item, "reviewDigest"));
                    var owner = List.of(context.id(), pin.relationInputDigest(), pin.upstreamJobId(), pin.upstreamInputDigest(), pin.upstreamDigest());
                    var priorOwner = jobs.putIfAbsent(pin.relationJobId(), owner);
                    if (pins.put(pin, context) != null || (priorOwner != null && !priorOwner.equals(owner))) throw new StrictJson.Malformed();
                    var identity = List.of(context.id(), pin.upstreamInputDigest(), pin.upstreamDigest());
                    var previous = upstreams.putIfAbsent(pin.upstreamJobId(), identity);
                    if (previous != null && !previous.equals(identity)) throw new StrictJson.Malformed();
                }
                for (var ref : refs) {
                    ref.exactly(OBSERVATION);
                    Observation observation = new Observation(text(ref, "roundId"), text(ref, "sourceId"), ref.count("page"),
                            ref.count("ordinal"), text(ref, "documentId"), hash(ref, "rawVersion"), hash(ref, "documentVersion"));
                    if (observations.put(observation, context) != null) throw new StrictJson.Malformed();
                }
            }
            if (contexts.isEmpty()) throw new StrictJson.Malformed();
            HandoffSourceContexts result = new HandoffSourceContexts(file, sha256, contexts, pins, observations);
            List<Path> roots = result.roots();
            for (int i = 0; i < roots.size(); i++) {
                Path candidate = roots.get(i);
                if (!Files.isDirectory(candidate) || !candidate.equals(candidate.toRealPath())) throw new StrictJson.Malformed();
                for (int j = 0; j < i; j++) {
                    if (candidate.startsWith(roots.get(j)) || roots.get(j).startsWith(candidate)) throw new StrictJson.Malformed();
                }
                if (file.startsWith(candidate)) throw new StrictJson.Malformed();
                for (Context context : contexts) if (context.sources().startsWith(candidate)) throw new StrictJson.Malformed();
            }
            return result;
        } catch (IOException | IllegalArgumentException | StrictJson.Malformed error) {
            throw new GraphHandoffImportConfigurationException("source-contexts", "must be a valid pinned context inventory");
        }
    }

    private static byte[] readBytes(Path file) throws IOException {
        for (Path walk = file; walk != null; walk = walk.getParent()) {
            if (Files.isSymbolicLink(walk)) throw new IOException();
        }
        if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS) || Files.size(file) > MAX_BYTES) throw new IOException();
        if (Files.getFileStore(file).supportsFileAttributeView("posix")) {
            var permissions = Files.getPosixFilePermissions(file, LinkOption.NOFOLLOW_LINKS);
            if (permissions.contains(PosixFilePermission.GROUP_WRITE) || permissions.contains(PosixFilePermission.OTHERS_WRITE)) throw new IOException();
        }
        try (var input = Files.newInputStream(file, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = input.readNBytes(MAX_BYTES + 1);
            if (bytes.length > MAX_BYTES) throw new IOException();
            return bytes;
        }
    }

    private static String text(StrictJson.Obj node, String key) {
        String value = node.string(key);
        if (value.isEmpty() || Text.codePoints(value) > 200 || Text.strictUtf8(value) == null) throw new StrictJson.Malformed();
        return value;
    }

    private static String job(StrictJson.Obj node) {
        String value = node.string("jobId");
        if (!ID.matcher(value).matches()) throw new StrictJson.Malformed();
        return value;
    }

    private static String hash(StrictJson.Obj node, String key) {
        String value = node.string(key);
        if (!StrictJson.SHA256.matcher(value).matches()) throw new StrictJson.Malformed();
        return value;
    }

    private static Path path(StrictJson.Obj node, String key) {
        Path path = Path.of(node.string(key));
        if (!path.isAbsolute() || !path.equals(path.normalize())) throw new StrictJson.Malformed();
        return path;
    }

    public List<Path> roots() {
        return contexts.stream().flatMap(context -> java.util.stream.Stream.of(context.relation(), context.extraction(), context.ingestion())).toList();
    }

    public Context observation(Observation observation) {
        unchanged();
        Context context = observations.get(observation);
        if (context == null) throw GraphHandoffException.handoffRefused("source_context_observation_missing");
        return context;
    }

    public void selected(HandoffBundle bundle) {
        unchanged();
        for (SourcePin pin : bundle.sources()) {
            if (!pins.containsKey(pin)) throw GraphHandoffException.handoffRefused("source_context_pin_missing");
        }
    }

    public void unchanged() {
        try {
            if (!Canonical.sha256(readBytes(file)).equals(sha256)) throw new IOException();
        } catch (IOException | RuntimeException error) {
            throw GraphHandoffException.handoffRefused("source_contexts_changed");
        }
    }
}
