package com.zoop.chat.tool;

import java.util.List;

/** One thing a tool found: its id and kind, display label, linked company ids and the readable evidence it carries. */
public record ChatToolItem(String id, String kind, String label, List<String> companyIds, List<String> evidenceIds) {
    public ChatToolItem {
        companyIds = List.copyOf(companyIds);
        evidenceIds = List.copyOf(evidenceIds);
    }
}
