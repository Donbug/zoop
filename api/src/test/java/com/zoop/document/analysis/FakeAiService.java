package com.zoop.document.analysis;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Executors;
import java.util.function.Function;

import com.sun.net.httpserver.HttpServer;
import com.zoop.ai.AiClientSettings;
import com.zoop.ai.http.HttpAiAnalysisClient;

/**
 * A real loopback HTTP server that plays the AI service for the analysis tests: the app talks to it through the REAL
 * {@link HttpAiAnalysisClient} (so every status, error envelope and result is decoded by the production wire reader) while the
 * tests decide what each request answers. It records every request, so "no second submit" and "no call at all" are observable.
 */
final class FakeAiService implements AutoCloseable {
    static final String TOKEN = "test-token-0123456789abcdefghijklmnopqrstuvwxyz";

    record Request(String method, String path, String requestId, String body) {
        boolean is(String method, String suffix) {
            return this.method.equals(method) && path.endsWith(suffix);
        }
    }

    record Reply(int status, String body) {
        static Reply json(int status, String body) {
            return new Reply(status, body);
        }
    }

    private final HttpServer server;
    final List<Request> requests = new CopyOnWriteArrayList<>();
    private volatile Function<Request, Reply> handler = request -> Reply.json(500, "{}");

    FakeAiService() throws IOException {
        server = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0);
        server.setExecutor(Executors.newCachedThreadPool());
        server.createContext("/", exchange -> {
            String requestId = exchange.getRequestHeaders().getFirst("X-Request-ID");
            Request request = new Request(exchange.getRequestMethod(), exchange.getRequestURI().getRawPath(), requestId,
                    new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            requests.add(request);
            Reply reply = handler.apply(request);
            byte[] body = reply.body().getBytes(StandardCharsets.UTF_8);
            try {
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                if (requestId != null) {
                    exchange.getResponseHeaders().set("X-Request-ID", requestId);
                }
                exchange.sendResponseHeaders(reply.status(), body.length == 0 ? -1 : body.length);
                try (OutputStream out = exchange.getResponseBody()) {
                    out.write(body);
                }
            } catch (IOException ignored) {
                // the client gave up: nothing to answer
            } finally {
                exchange.close();
            }
        });
        server.start();
    }

    void respond(Function<Request, Reply> handler) {
        this.handler = handler;
    }

    HttpAiAnalysisClient client() {
        return new HttpAiAnalysisClient(AiClientSettings.of("http://127.0.0.1:" + server.getAddress().getPort(), TOKEN,
                Duration.ofSeconds(2), Duration.ofSeconds(10), 8 * 1024 * 1024));
    }

    List<Request> calls(String method, String suffix) {
        return requests.stream().filter(request -> request.is(method, suffix)).toList();
    }

    /** The service's error envelope ({@code zoop-ai-internal-1}) for the request being answered. */
    static String error(String code, boolean retryable, Request request) {
        return "{\"schemaVersion\":\"zoop-ai-internal-1\",\"error\":{\"code\":\"" + code + "\",\"retryable\":" + retryable
                + ",\"requestId\":\"" + request.requestId() + "\",\"runtimeCode\":null,\"field\":null},\"status\":null}";
    }

    @Override
    public void close() {
        server.stop(0);
        ((java.util.concurrent.ExecutorService) server.getExecutor()).shutdownNow();
    }
}
