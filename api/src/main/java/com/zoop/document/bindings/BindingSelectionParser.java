package com.zoop.document.bindings;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.bindings.BindingSelection.VersionKey;

/**
 * Strict reader of the optional selection file. The key sets are exact, every id has the S2-1 shape, the list has one to
 * {@link DocumentBindingsExporter#MAX_BINDINGS} entries and no version twice. Anything else is {@code selection_invalid}.
 */
public final class BindingSelectionParser {
    public static final String SCHEMA_VERSION = "zoop-document-bindings-selection-1";
    /** The selection file never needs to be larger than the bindings file the AI runtime accepts. */
    public static final int MAX_BYTES = DocumentBindingsExporter.MAX_BYTES;
    private static final Set<String> ROOT = Set.of("schemaVersion", "versions");
    private static final Set<String> VERSION = Set.of("documentId", "documentVersion");

    public BindingSelection parse(byte[] bytes) {
        try {
            Obj root = StrictJson.parseObject(bytes).exactly(ROOT);
            if (!SCHEMA_VERSION.equals(root.string("schemaVersion"))) {
                throw new DocumentBindingsException(DocumentBindingsFailure.SELECTION_INVALID);
            }
            List<Obj> entries = root.objects("versions");
            if (entries.isEmpty() || entries.size() > DocumentBindingsExporter.MAX_BINDINGS) {
                throw new DocumentBindingsException(DocumentBindingsFailure.SELECTION_INVALID);
            }
            List<VersionKey> versions = new ArrayList<>(entries.size());
            Set<VersionKey> seen = new HashSet<>();
            for (Obj entry : entries) {
                entry.exactly(VERSION);
                VersionKey key = new VersionKey(entry.string("documentId"), entry.string("documentVersion"));
                if (!DocumentBindingsExporter.ARTICLE_ID.matcher(key.documentId()).matches()
                        || !StrictJson.SHA256.matcher(key.documentVersion()).matches() || !seen.add(key)) {
                    throw new DocumentBindingsException(DocumentBindingsFailure.SELECTION_INVALID);
                }
                versions.add(key);
            }
            return new BindingSelection(versions);
        } catch (StrictJson.Malformed malformed) {
            throw new DocumentBindingsException(DocumentBindingsFailure.SELECTION_INVALID);
        }
    }
}
