package com.zoop.ai.http;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Executors;
import java.util.function.Function;

import com.sun.net.httpserver.HttpServer;

/** A real loopback HTTP server standing in for ai/service in protocol tests: it counts and records every request. */
final class StubAiServer implements AutoCloseable {
    static final String TOKEN = "test-token-0123456789abcdefghijklmnopqrstuvwxyz";
    static final String DIGEST = "0".repeat(64);

    record Seen(String method, String path, Map<String, List<String>> headers, String body) {
        String header(String name) {
            return headers.entrySet().stream().filter(e -> e.getKey().equalsIgnoreCase(name)).findFirst()
                    .map(e -> e.getValue().get(0)).orElse(null);
        }

        String requestId() {
            return header("X-Request-ID");
        }
    }

    static final class Reply {
        final int status;
        final byte[] body;
        final Map<String, String> headers = new LinkedHashMap<>();
        boolean echoRequestId = true;
        long delayBeforeHeadersMs;
        long stallAfterPartialBodyMs;
        boolean chunked;

        private Reply(int status, byte[] body) {
            this.status = status;
            this.body = body;
            headers.put("Content-Type", "application/json");
        }

        static Reply json(int status, String body) {
            return new Reply(status, body.getBytes(StandardCharsets.UTF_8));
        }

        static Reply bytes(int status, byte[] body) {
            return new Reply(status, body);
        }

        Reply header(String name, String value) {
            headers.put(name, value);
            return this;
        }

        Reply withoutEcho() {
            echoRequestId = false;
            return this;
        }

        Reply delay(long millis) {
            delayBeforeHeadersMs = millis;
            return this;
        }

        Reply stallBody(long millis) {
            stallAfterPartialBodyMs = millis;
            return this;
        }

        Reply chunked() {
            chunked = true;
            return this;
        }
    }

    private final HttpServer server;
    final List<Seen> requests = new CopyOnWriteArrayList<>();
    private volatile Function<Seen, Reply> handler = seen -> Reply.json(500, "{}");

    StubAiServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0);
        server.setExecutor(Executors.newCachedThreadPool());
        server.createContext("/", exchange -> {
            Map<String, List<String>> headers = new LinkedHashMap<>();
            exchange.getRequestHeaders().forEach((k, v) -> headers.put(k, new ArrayList<>(v)));
            Seen seen = new Seen(exchange.getRequestMethod(), exchange.getRequestURI().getRawPath(), headers,
                    new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            requests.add(seen);
            Reply reply = handler.apply(seen);
            try {
                if (reply.delayBeforeHeadersMs > 0) {
                    Thread.sleep(reply.delayBeforeHeadersMs);
                }
                reply.headers.forEach((k, v) -> exchange.getResponseHeaders().set(k, v));
                if (reply.echoRequestId && seen.requestId() != null) {
                    exchange.getResponseHeaders().set("X-Request-ID", seen.requestId());
                }
                exchange.sendResponseHeaders(reply.status, reply.chunked ? 0 : (reply.body.length == 0 ? -1 : reply.body.length));
                try (OutputStream out = exchange.getResponseBody()) {
                    if (reply.stallAfterPartialBodyMs > 0) {
                        out.write(reply.body, 0, Math.min(10, reply.body.length));
                        out.flush();
                        Thread.sleep(reply.stallAfterPartialBodyMs);
                        out.write(reply.body, Math.min(10, reply.body.length), Math.max(0, reply.body.length - 10));
                    } else {
                        out.write(reply.body);
                    }
                }
            } catch (IOException | InterruptedException ignored) {
                // the client gave up (timeout/limit): nothing to answer
            } finally {
                exchange.close();
            }
        });
        server.start();
    }

    void respond(Function<Seen, Reply> handler) {
        this.handler = handler;
    }

    void respond(Reply reply) {
        this.handler = seen -> reply;
    }

    String baseUrl() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    @Override
    public void close() {
        server.stop(0);
        ((java.util.concurrent.ExecutorService) server.getExecutor()).shutdownNow();
    }

    // ---- wire documents ----

    static String status(String jobId, String state, String next) {
        return status(jobId, state, next, "0", "0");
    }

    static String status(String jobId, String state, String next, String providerAttempts, String unreceipted) {
        return statusFor(jobId, "document-summary", "replay", state, next, providerAttempts, unreceipted);
    }

    static String statusFor(String jobId, String kind, String mode, String state, String next) {
        return statusFor(jobId, kind, mode, state, next, "0", "0");
    }

    static String statusFor(String jobId, String kind, String mode, String state, String next, String providerAttempts,
                         String unreceipted) {
        return """
                {"schemaVersion":"zoop-ai-internal-1","jobId":"%s","kind":"%s","mode":"%s","inputDigest":"%s",\
                "state":"%s","phase":"input.persisted","resumeMode":"unsent_only","failure":null,"artifactIds":[],\
                "usage":{"providerAttempts":%s,"replayCalls":0,"inputTokens":null,"outputTokens":null,"cachedTokens":null,\
                "reasoningTokens":null,"cost":null},"unreceiptedAttempts":%s,\
                "dispatch":{"state":"pending","command":"run","dispatchCount":0,"lastOutcome":null,"lastRuntimeCode":null,\
                "updatedAt":"2026-10-12T03:00:00Z"},"next":"%s","acceptedAt":"2026-10-12T03:00:00Z",\
                "observedAt":"2026-10-12T03:00:00Z"}""".formatted(jobId, kind, mode, DIGEST, state, providerAttempts, unreceipted, next);
    }

    static String error(String code, boolean retryable, String requestId, String field, String statusJson) {
        return """
                {"schemaVersion":"zoop-ai-internal-1","error":{"code":"%s","retryable":%s,"requestId":"%s","runtimeCode":null,\
                "field":%s},"status":%s}""".formatted(code, retryable, requestId, field == null ? "null" : "\"" + field + "\"",
                statusJson == null ? "null" : statusJson);
    }

    static String result(String jobId, String state, String delivery, String reason, String job, String receipts) {
        return """
                {"schemaVersion":"zoop-ai-internal-1","status":%s,"delivery":{"state":"%s","reason":%s},"job":%s,"receipts":%s}"""
                .formatted(status(jobId, state, "fetch_result"), delivery, reason == null ? "null" : "\"" + reason + "\"",
                        job == null ? "null" : job, receipts);
    }

    static String job(String jobId, String state) {
        return """
                {"schemaVersion":"zoop-ai-s1-1","jobId":"%s","inputDigest":"%s","state":"%s",\
                "input":{"kind":"document-summary","mode":"replay"},"artifacts":[{"result":{"text":"UNTRUSTED-MODEL-TEXT"}}]}"""
                .formatted(jobId, DIGEST, state);
    }

    static final String RECEIPT = """
            {"attemptId":"attempt-1","stage":"document-summary","state":"received","mode":"replay","startedAt":"2026-10-12T03:00:00.263955+00:00",\
            "receivedAt":"2026-10-12T03:00:01.264951+00:00","inputDigest":"%s","config":{"provider":"authored-replay","providerRevision":"r1",\
            "model":"replay","reasoningEffort":null,"promptVersion":"p-1","schemaVersion":"s-1","policyVersion":"v-1"},\
            "usage":{"inputTokens":3,"outputTokens":4,"cachedTokens":null,"reasoningTokens":null},"error":null,"durationMs":12.5}"""
            .formatted(DIGEST);
}
