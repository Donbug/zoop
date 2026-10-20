package com.zoop.graph.read;

import com.zoop.graph.snapshot.PublicGraphSnapshot.Basis;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.Collection;

/**
 * FS042 business relation status at a reference time (asOf, else the request time). The time becomes its Asia/Seoul
 * date D and only dates are compared; a source date never gets a time or an extra day. validUntil is the last valid
 * day (inclusive); a null validUntil means the end is unknown, so the relation is not ended. The status never decides
 * whether a relation is shown.
 */
final class RelationValidity {
    static final String SCHEDULED = "scheduled";
    static final String ACTIVE = "active";
    static final String ENDED = "ended";
    static final String UNKNOWN = "unknown";
    private static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");

    private RelationValidity() {
    }

    static String of(Basis b, Instant at) {
        LocalDate day = LocalDate.ofInstant(at, SEOUL);
        if (b.validUntil() != null && day.isAfter(LocalDate.parse(b.validUntil()))) return ENDED;
        if (b.validFrom() == null) return UNKNOWN;
        return day.isBefore(LocalDate.parse(b.validFrom())) ? SCHEDULED : ACTIVE;
    }

    /** An edge resting on several bases: active if any is, else scheduled, else unknown, ended only when all are; null without bases. */
    static String of(Collection<Basis> bases, Instant at) {
        if (bases.isEmpty()) return null;
        var statuses = bases.stream().map(b -> of(b, at)).toList();
        for (String status : new String[] {ACTIVE, SCHEDULED, UNKNOWN}) {
            if (statuses.contains(status)) return status;
        }
        return ENDED;
    }
}
