package com.zoop.document.evidence.service;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.document.repository.ArtifactRow;

/**
 * Verified, read-only access to the two artifact kinds the public read may need: the exact receipt of a cache-served summary and
 * the import {@code verification_receipt} of the graph version being served. It reads through
 * {@link ArtifactFileStore#readVerified}: no lock, no session, nothing is created, repaired or deleted, and the file must match the
 * registry's hash and size. Without a configured artifact root every read is
 * {@link ArtifactStoreException.Reason#UNAVAILABLE}.
 */
public final class EvidenceArtifactReader {
    private final ArtifactFileStore store;

    /** @param store the store at {@code zoop.document-read.artifact-root}, or {@code null} when it is not set */
    public EvidenceArtifactReader(ArtifactFileStore store) {
        this.store = store;
    }

    public byte[] read(ArtifactRow artifact) {
        if (store == null) {
            throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "root_unset");
        }
        return store.readVerified(artifact.storageUri(), artifact.sha256(), artifact.bytes());
    }
}
