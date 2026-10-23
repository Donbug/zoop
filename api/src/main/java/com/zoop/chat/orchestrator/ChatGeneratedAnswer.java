package com.zoop.chat.orchestrator;

import java.util.List;

/**
 * The generator's typed answer ({@code ChatGeneratedAnswer}): sections by basis, each belonging to the requirements it
 * answers, the requirements it could not answer from the evidence, and the map targets the text points at. It proposes no
 * {@code answerBasis}, citation text or limitation message: the server derives those.
 */
public record ChatGeneratedAnswer(List<Section> sections, List<String> insufficientRequirementIds,
        List<String> graphTargetIds) {
    public ChatGeneratedAnswer {
        sections = sections == null ? List.of() : List.copyOf(sections);
        insufficientRequirementIds = insufficientRequirementIds == null ? List.of() : List.copyOf(insufficientRequirementIds);
        graphTargetIds = graphTargetIds == null ? List.of() : List.copyOf(graphTargetIds);
    }

    /**
     * One section at one basis ({@code general_knowledge} or {@code evidence_grounded}). It belongs to one requirement, or to
     * several when it only joins them; {@code evidenceIds} are the evidence its claims rest on.
     */
    public record Section(String basis, String text, List<String> requirementIds, List<String> evidenceIds) {
        public Section {
            requirementIds = requirementIds == null ? List.of() : List.copyOf(requirementIds);
            evidenceIds = evidenceIds == null ? List.of() : List.copyOf(evidenceIds);
        }
    }
}
