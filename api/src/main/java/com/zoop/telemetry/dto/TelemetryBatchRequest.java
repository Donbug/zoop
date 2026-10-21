package com.zoop.telemetry.dto;

import java.util.List;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public record TelemetryBatchRequest(
        @NotEmpty @Size(max = 20) List<@NotNull @Valid TelemetryEventRequest> events) {
}
