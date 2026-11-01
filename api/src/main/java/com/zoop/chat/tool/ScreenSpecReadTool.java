package com.zoop.chat.tool;

import com.zoop.chat.service.ChatZoopDocs;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/** Q01 screen guide, bound only after an operator enables the approved-document gate. */
@Component
@ConditionalOnProperty(name = "zoop.chat.approved-docs.enabled", havingValue = "true")
public final class ScreenSpecReadTool extends ZoopDocumentReadTool {
    public ScreenSpecReadTool(ChatZoopDocs docs) {
        super(docs, ChatCapability.SCREEN_SPEC_READ, true);
    }
}
