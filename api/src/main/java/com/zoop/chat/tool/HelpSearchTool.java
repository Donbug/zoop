package com.zoop.chat.tool;

import com.zoop.chat.service.ChatZoopDocs;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/** Q01 member help, bound only after an operator enables the approved-document gate. */
@Component
@ConditionalOnProperty(name = "zoop.chat.approved-docs.enabled", havingValue = "true")
public final class HelpSearchTool extends ZoopDocumentReadTool {
    public HelpSearchTool(ChatZoopDocs docs) {
        super(docs, ChatCapability.HELP_SEARCH, true);
    }
}
