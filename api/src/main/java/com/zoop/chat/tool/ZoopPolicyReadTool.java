package com.zoop.chat.tool;

import com.zoop.chat.service.ChatZoopDocs;
import org.springframework.stereotype.Component;

/**
 * {@code zoopPolicy.read}: the approved ZOOP policies in effect at the run's asOf (now without one) and still in effect now
 * ({@link ChatZoopDocs#inEffect}), each as an item with its
 * sections passed on as evidence in body order, kept within the request's evidence scope and capped at the request limit.
 * Its targets are always {@link ChatZoopDocs#POLICIES} ({@link ChatCapability#documents()}); a target that is not a policy
 * in effect is absent. It reads no graph. The data version names each policy version read. A registry that cannot be read
 * is {@link ChatToolUnavailable}, never an empty result.
 */
@Component
public class ZoopPolicyReadTool extends ZoopDocumentReadTool {
    public ZoopPolicyReadTool(ChatZoopDocs docs) {
        super(docs, ChatCapability.ZOOP_POLICY_READ, false);
    }
}
