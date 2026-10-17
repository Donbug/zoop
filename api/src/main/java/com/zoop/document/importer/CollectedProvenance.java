package com.zoop.document.importer;

import java.time.Instant;

/**
 * Acquisition facts of an S2-1 export whose observation was <em>collected over HTTP</em> by {@code zoop-ai-collect}. Absent
 * (null in {@link VerifiedDocument}) for authored fixtures, whose export has none of these keys.
 *
 * <p>These facts come from an unsigned, operator-owned receipt that the ledger checked for consistency with the stored bytes
 * and the registry. They are an internally consistent record, not cryptographic proof that a fetch happened, and they are
 * not a license: rights stay with the grant.
 *
 * @param collectionId     the immutable collection run that fetched the bytes
 * @param receiptSha256    hash of the receipt file that pins this acquisition
 * @param bodySha256       hash of the fetched bytes; equals the export's {@code locatorMetadata.rawHash}
 * @param fetchedAt        actual completion time of the HTTP response (UTC instant)
 * @param finalUrl         the URL that answered after redirects
 * @param httpStatus       2xx status of the final response
 * @param contentType      the response's Content-Type header, verbatim
 * @param network          {@code external}, or {@code synthetic_loopback} for bytes a local synthetic test server produced; the
 *                         latter must never be presented as an external document
 * @param documentKind     {@code news} or {@code disclosure}, as the operator declared it in the collection request
 * @param declaredPrecision how the operator-declared publication time was classified: {@code instant}, {@code day},
 *                         {@code unresolved} (a time without an offset; the timezone is never assumed) or {@code unknown}
 * @param declaredRaw      the declared publication time exactly as written, or null when none was declared
 * @param declaredBasis    the ledger's one-line statement of what that classification does and does not claim
 */
public record CollectedProvenance(String collectionId, String receiptSha256, String bodySha256, Instant fetchedAt,
        String finalUrl, int httpStatus, String contentType, String network, String documentKind, String declaredPrecision,
        String declaredRaw, String declaredBasis) {

    public static final String PROVENANCE = "collected_http";
}
