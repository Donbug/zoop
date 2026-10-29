package com.zoop.chat.repository;

import java.time.Instant;

/**
 * A job that is running now under an unexpired lease: its row, the run's owner token and deadline. Only the server reads
 * the owner token; it is never sent anywhere.
 */
public record ChatRunningJob(ChatJobRow job, String ownerToken, Instant deadline) { }
