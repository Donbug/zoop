package com.zoop.chat.repository;

/** A succeeded MCP call of an attempt with the normalized result it returned to the model ({@code chat_tool_calls.result}). */
public record ChatKeptToolResult(String toolCallId, String capabilityId, String result) { }
