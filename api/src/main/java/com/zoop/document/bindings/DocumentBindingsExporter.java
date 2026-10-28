package com.zoop.document.bindings;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.regex.Pattern;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.bindings.BindingSelection.VersionKey;
import com.zoop.document.bindings.DocumentBindingsRepository.BindingRow;
import org.springframework.dao.DataAccessException;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Builds the operator file the AI handoff {@code freeze} binds documents with ({@code zoop-app-document-bindings-1}, the
 * {@code --bindings} argument of {@code zoop-ai-handoff}): for every registered article version, that this exact S2-1 document
 * version IS this app article version, whose stored UTF-8 text has this SHA-256 and is cited in Unicode code points.
 *
 * <p>Nothing is invented: the document import registers {@code articles.id} as the S2-1 {@code documentId},
 * {@code article_versions.version} as the {@code documentVersion} and the text artifact {@code text-<documentVersion>} with the
 * SHA-256 of the stored UTF-8 bytes (api/docs/DOCUMENT_IMPORT.md), and the graph import verifies a bundle's
 * {@code article.textSha256} against that same artifact hash. The export is a projection of those rows, in canonical JSON
 * ({@link Canonical#bytes}: sorted keys, no whitespace), so the same registry state always gives the same bytes and the same
 * file hash, which is what the freeze manifest pins.
 *
 * <p>The AI contract's limits and shapes are enforced here, fail closed: at most {@link #MAX_BINDINGS} entries and
 * {@link #MAX_BYTES} bytes (one binding is about 452 bytes, so the byte limit binds first, at roughly 8,800 entries),
 * {@code doc-<64hex>} ids, {@code <64hex>} versions and hashes, and only an {@code extracted_text} artifact may back a binding.
 * A row that breaks the identity rule the import guarantees ({@code text_artifact_id} is {@code text-} + version) refuses the
 * whole export rather than binding a text the AI runtime would then hash differently.
 */
public final class DocumentBindingsExporter {
    /** {@code zoop_ai_pipeline.handoff_contracts.BINDINGS_SCHEMA}. */
    public static final String SCHEMA_VERSION = "zoop-app-document-bindings-1";
    /** The only {@code offsetUnit} the AI contract accepts; the app's evidence offsets are code points. */
    public static final String OFFSET_UNIT = "unicode_code_point";
    /** {@code handoff_contracts.MAX_DECISIONS}: the most entries a bindings file may hold. */
    public static final int MAX_BINDINGS = 20_000;
    /** {@code handoff_contracts.MAX_OPERATOR_FILE}: the most bytes the freeze reads of an operator file. */
    public static final int MAX_BYTES = 4_000_000;
    /** The S2-1 document id shape ({@code handoff_contracts.ARTICLE_ID}), as the document import's own parsers also state it. */
    static final Pattern ARTICLE_ID = Pattern.compile("doc-[a-f0-9]{64}");
    static final String AVAILABLE = "available";
    static final String TEXT_KIND = "extracted_text";
    private static final String TEXT_PREFIX = "text-";

    private final DocumentBindingsRepository repository;

    public DocumentBindingsExporter(DocumentBindingsRepository repository) {
        this.repository = repository;
    }

    /**
     * The file bytes, their SHA-256, how many bindings they hold and, per access status, how many registered versions the scope
     * left out. {@link #bytes()} is a copy of the exact content to hand to the AI runtime; {@link #size()} is its length.
     */
    public record Export(byte[] bytes, String sha256, int count, Map<String, Integer> excluded) {
        public Export {
            bytes = bytes.clone();
            excluded = Map.copyOf(excluded);
        }

        @Override
        public byte[] bytes() {
            return bytes.clone();
        }

        public int size() {
            return bytes.length;
        }
    }

    /**
     * @param scope     which versions to bind
     * @param selection an explicit list of versions to bind instead of every registered one, or {@code null}; every one of
     *                  them must be registered ({@code selection_unregistered} otherwise), and the scope still applies
     */
    public Export export(DocumentBindingsScope scope, BindingSelection selection) {
        boolean availableOnly = scope == DocumentBindingsScope.AVAILABLE;
        List<BindingRow> rows;
        Map<String, Integer> excluded = new TreeMap<>();
        try {
            if (selection == null) {
                // The scope is pushed into the statement; the versions it leaves out are only counted, never fetched.
                rows = new ArrayList<>(repository.listVersions(availableOnly));
                if (availableOnly) {
                    excluded.putAll(repository.countExcludedByStatus());
                }
            } else {
                rows = select(repository.findVersions(selection.versions()), selection);
            }
        } catch (DataAccessException unavailable) {
            throw new DocumentBindingsException(DocumentBindingsFailure.DATABASE_UNAVAILABLE);
        }
        rows.sort(Comparator.comparing(BindingRow::articleId).thenComparing(BindingRow::version));

        List<BindingRow> bound = new ArrayList<>();
        for (BindingRow row : rows) {
            if (availableOnly && !AVAILABLE.equals(row.accessStatus())) {
                excluded.merge(row.accessStatus(), 1, Integer::sum);
                continue;
            }
            check(row);
            bound.add(row);
        }
        if (bound.size() > MAX_BINDINGS) {
            throw new DocumentBindingsException(DocumentBindingsFailure.BINDINGS_LIMIT);
        }

        ObjectNode root = StrictJson.newObject();
        root.put("schemaVersion", SCHEMA_VERSION);
        ArrayNode bindings = root.putArray("bindings");
        for (BindingRow row : bound) {
            ObjectNode node = bindings.addObject();
            node.put("documentId", row.articleId());
            node.put("documentVersion", row.version());
            node.put("articleId", row.articleId());
            node.put("articleVersion", row.version());
            node.put("textSha256", row.textSha256());
            node.put("offsetUnit", OFFSET_UNIT);
        }
        byte[] bytes = Canonical.bytes(root);
        if (bytes.length > MAX_BYTES) {
            throw new DocumentBindingsException(DocumentBindingsFailure.BINDINGS_LIMIT);
        }
        return new Export(bytes, Canonical.sha256(bytes), bound.size(), excluded);
    }

    /** The registered rows of exactly the selected versions, one each; a version without a row refuses the run. */
    private static List<BindingRow> select(List<BindingRow> found, BindingSelection selection) {
        Map<VersionKey, BindingRow> byKey = new HashMap<>();
        for (BindingRow row : found) {
            byKey.put(new VersionKey(row.articleId(), row.version()), row);
        }
        List<BindingRow> chosen = new ArrayList<>(selection.versions().size());
        for (VersionKey key : selection.versions()) {
            BindingRow row = byKey.get(key);
            if (row == null) {
                throw new DocumentBindingsException(DocumentBindingsFailure.SELECTION_UNREGISTERED);
            }
            chosen.add(row);
        }
        return chosen;
    }

    /** The identity the document import guarantees and the shapes the AI contract requires, or the export is refused. */
    private static void check(BindingRow row) {
        if (row.articleId() == null || row.version() == null || row.textArtifactId() == null || row.textSha256() == null
                || !ARTICLE_ID.matcher(row.articleId()).matches() || !StrictJson.SHA256.matcher(row.version()).matches()
                || !StrictJson.SHA256.matcher(row.textSha256()).matches()
                || !row.textArtifactId().equals(TEXT_PREFIX + row.version())) {
            throw new DocumentBindingsException(DocumentBindingsFailure.IDENTITY_INVALID);
        }
        if (!TEXT_KIND.equals(row.artifactKind())) {
            throw new DocumentBindingsException(DocumentBindingsFailure.ARTIFACT_KIND_INVALID);
        }
    }
}
