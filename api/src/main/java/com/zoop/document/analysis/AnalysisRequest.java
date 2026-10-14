package com.zoop.document.analysis;

import java.util.List;

import com.zoop.ai.AnalysisKind;
import com.zoop.ai.ExecutionMode;
import com.zoop.document.importer.Observation;

/** A validated batch of 1 to {@value #MAX_ITEMS} items of one command, run in order. */
public sealed interface AnalysisRequest {
    int MAX_ITEMS = 100;

    String command();

    int size();

    /** The grant of the flat S1 registry the operator declares for this analysis: id and the exact revision. */
    record GrantRef(String grantId, String revision) {
    }

    /**
     * One analysis to reserve. {@code observation} selects the S2-1 document exactly as for the document import;
     * {@code companyId} is the operator-declared company context (never inferred); {@code expectedLatest} is the
     * compare-and-set value: the id of the latest analysis of the scope, or null for "none yet".
     */
    record PrepareItem(Observation observation, AnalysisKind kind, String companyId, GrantRef grant, ExecutionMode mode,
            String sourceKind, String expectedLatest) {
    }

    /** One reserved analysis to move forward; {@code recover} is the only way a run asks the AI service to recover a job. */
    record AdvanceItem(String analysisId, boolean recover) {
    }

    record Prepare(List<PrepareItem> items) implements AnalysisRequest {
        public Prepare {
            items = List.copyOf(items);
        }

        @Override
        public String command() {
            return "prepare";
        }

        @Override
        public int size() {
            return items.size();
        }
    }

    record Advance(List<AdvanceItem> items) implements AnalysisRequest {
        public Advance {
            items = List.copyOf(items);
        }

        @Override
        public String command() {
            return "advance";
        }

        @Override
        public int size() {
            return items.size();
        }
    }
}
