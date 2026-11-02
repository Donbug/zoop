package com.zoop.graph.delivery;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.Text;
import com.zoop.document.repository.ArtifactRow;
import tools.jackson.databind.node.ObjectNode;

/** Exact canonical bytes and closed file identities; the manifest conveys integrity, not current rights. */
public record GraphDeliveryManifest(String versionId, String destinationId, String handoffId, String manifestDigest,
        String bundleDigest, String publicationId, String publicationReceiptSha256, List<FilePin> files) {
    public static final String SCHEMA = "zoop-graph-delivery-package-2";
    public static final String PUBLICATION_SCHEMA = "zoop-graph-delivery-package-3";
    private static final Pattern DESTINATION = Pattern.compile("[a-z0-9][a-z0-9-]{0,63}");
    private static final Pattern NAME = Pattern.compile("[A-Za-z0-9][A-Za-z0-9_-]{0,127}\\.[a-z0-9]{1,8}");
    private static final Map<String, String> DIRECTORIES = Map.of("graph_snapshot", "graph_snapshot",
            "verification_receipt", "verification_receipt", "extracted_text", "extracted_text",
            "graph_bundle_snapshot", "graph_bundle");
    private static final Set<String> ROOT = Set.of("schemaVersion", "versionId", "destinationId", "handoffId",
            "manifestDigest", "bundleDigest", "files");
    private static final Set<String> PUBLICATION_ROOT = Set.of("schemaVersion", "versionId", "destinationId",
            "publicationId", "publicationReceiptSha256", "files");
    private static final Set<String> FILE = Set.of("artifactId", "kind", "storageUri", "sha256", "bytes", "mediaType");

    public GraphDeliveryManifest {
        if (publicationId == null) {
            require(publicationReceiptSha256 == null && handoffId != null && !handoffId.isBlank()
                    && handoffId.length() <= 200 && Text.strictUtf8(handoffId) != null);
            require(versionId != null && versionId.equals("gv-" + Canonical.sha256(handoffId)));
            require(digestValid(manifestDigest) && digestValid(bundleDigest));
        } else {
            require(publicationId.matches("publication:[0-9a-f]{64}") && digestValid(publicationReceiptSha256));
            require(versionId != null && versionId.equals("gv-" + Canonical.sha256(publicationId)));
            require(handoffId == null && manifestDigest == null && bundleDigest == null);
        }
        require(validDestination(destinationId));
        require(files != null && files.size() >= 2 && files.size() <= GraphDeliveryLimits.DEFAULT_MAX_FILES);
        files = List.copyOf(files);
        String previous = null;
        Set<String> uris = new HashSet<>();
        for (FilePin file : files) {
            require(previous == null || previous.compareTo(file.artifactId()) < 0);
            require(uris.add(file.storageUri()));
            previous = file.artifactId();
        }
    }

    public record FilePin(String artifactId, String kind, String storageUri, String sha256, long bytes, String mediaType) {
        public FilePin {
            require(artifactId != null && artifactId.matches("[A-Za-z0-9._:-]{1,200}"));
            require(kind != null && DIRECTORIES.containsKey(kind));
            String prefix = ArtifactFileStore.URI_SCHEME + DIRECTORIES.get(kind) + "/";
            require(storageUri != null && storageUri.startsWith(prefix)
                    && NAME.matcher(storageUri.substring(prefix.length())).matches());
            require(digestValid(sha256) && bytes >= 0 && bytes <= ArtifactFileStore.MAX_READ_BYTES);
            require(mediaType != null && !mediaType.isBlank() && mediaType.length() <= 200
                    && Text.strictUtf8(mediaType) != null);
        }

        public static FilePin from(ArtifactRow row) {
            return new FilePin(row.id(), row.kind(), row.storageUri(), row.sha256(), row.bytes(), row.mediaType());
        }
    }

    public static boolean validDestination(String value) {
        return value != null && DESTINATION.matcher(value).matches();
    }

    public static GraphDeliveryManifest build(String version, String destination, String handoff, String manifest,
            String bundle, List<ArtifactRow> rows) {
        return new GraphDeliveryManifest(version, destination, handoff, manifest, bundle, null, null,
                rows.stream().map(FilePin::from).sorted(Comparator.comparing(FilePin::artifactId)).toList());
    }

    public static GraphDeliveryManifest publication(String version, String destination, String publication,
            String receiptSha256, List<ArtifactRow> rows) {
        return new GraphDeliveryManifest(version, destination, null, null, null, publication, receiptSha256,
                rows.stream().map(FilePin::from).sorted(Comparator.comparing(FilePin::artifactId)).toList());
    }

    public boolean composed() { return publicationId != null; }

    public static GraphDeliveryManifest parse(byte[] bytes) {
        if (bytes == null || bytes.length == 0 || bytes.length > ArtifactFileStore.MAX_READ_BYTES) {
            throw new GraphDeliveryException("package_invalid");
        }
        try {
            StrictJson.Obj root = StrictJson.parseObject(bytes);
            boolean publication = PUBLICATION_SCHEMA.equals(root.string("schemaVersion"));
            require(publication || SCHEMA.equals(root.string("schemaVersion")));
            root.exactly(publication ? PUBLICATION_ROOT : ROOT);
            List<FilePin> files = new ArrayList<>();
            for (StrictJson.Obj file : root.objects("files")) {
                file.exactly(FILE);
                files.add(new FilePin(file.string("artifactId"), file.string("kind"), file.string("storageUri"),
                        file.string("sha256"), file.count("bytes"), file.string("mediaType")));
            }
            GraphDeliveryManifest manifest = new GraphDeliveryManifest(root.string("versionId"), root.string("destinationId"),
                    publication ? null : root.string("handoffId"), publication ? null : root.string("manifestDigest"),
                    publication ? null : root.string("bundleDigest"), publication ? root.string("publicationId") : null,
                    publication ? root.string("publicationReceiptSha256") : null, files);
            require(Arrays.equals(bytes, manifest.bytes()));
            return manifest;
        } catch (StrictJson.Malformed | IllegalArgumentException invalid) {
            throw new GraphDeliveryException("package_invalid");
        }
    }

    public byte[] bytes() {
        ObjectNode root = StrictJson.newObject();
        root.put("schemaVersion", composed() ? PUBLICATION_SCHEMA : SCHEMA);
        root.put("versionId", versionId);
        root.put("destinationId", destinationId);
        if (composed()) {
            root.put("publicationId", publicationId);
            root.put("publicationReceiptSha256", publicationReceiptSha256);
        } else {
            root.put("handoffId", handoffId);
            root.put("manifestDigest", manifestDigest);
            root.put("bundleDigest", bundleDigest);
        }
        var array = root.putArray("files");
        for (FilePin file : files) {
            ObjectNode node = array.addObject();
            node.put("artifactId", file.artifactId());
            node.put("kind", file.kind());
            node.put("storageUri", file.storageUri());
            node.put("sha256", file.sha256());
            node.put("bytes", file.bytes());
            node.put("mediaType", file.mediaType());
        }
        byte[] bytes = Canonical.bytes(root);
        if (bytes.length > ArtifactFileStore.MAX_READ_BYTES) throw new GraphDeliveryException("package_too_large");
        return bytes;
    }

    public String digest() { return Canonical.sha256(bytes()); }

    public long totalBytes() { return files.stream().mapToLong(FilePin::bytes).sum(); }

    private static boolean digestValid(String value) {
        return value != null && StrictJson.SHA256.matcher(value).matches();
    }

    private static void require(boolean condition) {
        if (!condition) throw new GraphDeliveryException("package_invalid");
    }
}
