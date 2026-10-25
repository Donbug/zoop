package com.zoop.admin.jobs;

import com.zoop.admin.audit.AuditReasonPolicy;
import com.zoop.ai.plan.PlanReference;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import java.io.IOException;
import java.io.InputStream;
import java.util.Set;

/** Only the executable new branch is closed; legacy shapes are recognized without adding an executor. */
public final class AnalyzePlanRequestParser {
    public static final int MAX_BYTES = 64 * 1024;
    private AnalyzePlanRequestParser() {}

    public static AnalyzePlanCommand parse(InputStream input) throws IOException {
        byte[] bytes = input.readNBytes(MAX_BYTES + 1);
        if (bytes.length > MAX_BYTES) throw new CustomException(ErrorCode.INVALID_REQUEST);
        try {
            var root = StrictJson.parseObject(bytes);
            String kind = root.string("kind");
            if (Set.of("ingest", "revalidate", "project").contains(kind)) {
                root.requiring(Set.of("kind", "reason"));
                checkedReason(root.string("reason"));
                if (root.has("sourceId") && !root.isNull("sourceId")) root.string("sourceId");
                if (root.has("candidateIds")) root.strings("candidateIds");
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, false);
            }
            if (!"analyze_plan".equals(kind)) throw new StrictJson.Malformed();
            root.exactly(Set.of("kind", "reason", "plan"));
            var plan = root.object("plan").exactly(Set.of("planId", "planDigest"));
            return new AnalyzePlanCommand(checkedReason(root.string("reason")),
                    new PlanReference(plan.string("planId"), plan.string("planDigest")));
        } catch (StrictJson.Malformed | IllegalArgumentException error) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
    }

    static String checkedReason(String raw) {
        String reason = raw.strip();
        if (!AuditReasonPolicy.safeMemberReason(reason)) throw new CustomException(ErrorCode.INVALID_REQUEST);
        return reason;
    }
}
