package com.zoop.admin.jobs;

import com.zoop.ai.plan.PlanReference;

public record AnalyzePlanCommand(String reason, PlanReference plan) {}
