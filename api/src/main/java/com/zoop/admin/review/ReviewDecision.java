package com.zoop.admin.review;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;

/** OpenAPI {@code DecisionRequest} and {@code DecisionResponse}. */
public final class ReviewDecision {
    private ReviewDecision() {
    }

    /** The three expected values are the decided target's (the relation's when {@code relationId} is set). */
    public record Request(
            @NotNull @Pattern(regexp = "allow|reject") String decision,
            @NotBlank @Size(max = 500) String reason,
            @Size(max = 200) String relationId,
            @NotNull @PositiveOrZero Long expectedRevision,
            @NotBlank @Size(max = 200) String expectedSourceVersion,
            @NotBlank @Pattern(regexp = "[0-9]{1,18}") String expectedSourceRevision) {
    }

    /** {@code decision} approved|rejected; {@code publicChanged} is always false: an approval is not a publication. */
    public record Response(String candidateId, String decision, long revision, boolean publicChanged) {
    }
}
