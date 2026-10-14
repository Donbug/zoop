package com.zoop.ai.http;

import java.net.ConnectException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpConnectTimeoutException;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Optional;
import java.util.OptionalInt;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.function.Supplier;
import java.util.regex.Pattern;

import com.zoop.ai.AiClientException;
import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.AiTransportException.Failure;
import com.zoop.ai.http.WireJson.Malformed;
import org.slf4j.MDC;
import tools.jackson.databind.JsonNode;

/**
 * The one low-level HTTP exchange every AI client family (S1 analysis, S2 extraction, S3 relation) shares: JDK
 * {@link HttpClient} over HTTP/1.1, no proxy, no redirect, no cookies, no authenticator, no retry. The bearer token is sent
 * only to the configured base URI. A call is bounded by the connect timeout, a total request deadline and a response size
 * limit, and the response must be UTF-8 JSON that echoes the request id. Family-specific schemas, identity checks and error
 * envelopes stay in the family's own wire decoder; this class never interprets them.
 *
 * <p>The request id is the current {@code requestId} MDC value (set by {@code RequestIdFilter}) when it fits the AI contract
 * ({@code [A-Za-z0-9._-]{1,128}}), otherwise a fresh UUID; an unsafe or oversized inbound id is never forwarded.
 */
final class AiHttpTransport implements AutoCloseable {
    /** MDC key written by {@code com.zoop.common.request.RequestIdFilter}. */
    static final String MDC_REQUEST_ID = "requestId";
    private static final Pattern JSON_MEDIA = Pattern.compile("application/json(\\s*;\\s*charset=\"?utf-8\"?)?", Pattern.CASE_INSENSITIVE);
    private static final Pattern SECONDS = Pattern.compile("[0-9]{1,7}");

    /** One accepted answer: the documented success status and its strictly parsed JSON object. */
    record Reply(int status, JsonNode body, Optional<Duration> retryAfter, String requestId, AiOperation operation) {
    }

    /**
     * Decodes a 4xx/5xx JSON answer into the family's typed exception. It must verify that the envelope's request id equals the
     * sent one and throw {@link Malformed} on any violation; {@code status} is the HTTP status.
     */
    @FunctionalInterface
    interface Rejections {
        AiClientException decode(JsonNode document, int status, Optional<Duration> retryAfter, AiOperation operation, String requestId);
    }

    private final AiClientSettings settings;
    private final HttpClient http;
    private final String authorization;
    private final String origin;
    private final String basePath;

    AiHttpTransport(AiClientSettings settings) {
        this.settings = settings;
        this.http = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .followRedirects(HttpClient.Redirect.NEVER)
                .proxy(HttpClient.Builder.NO_PROXY)
                .connectTimeout(settings.connectTimeout())
                .build();
        this.authorization = "Bearer " + settings.token();
        URI base = settings.baseUri();
        this.origin = base.getScheme().toLowerCase(java.util.Locale.ROOT) + "://" + base.getRawAuthority();
        String path = base.getRawPath() == null ? "" : base.getRawPath();
        this.basePath = path.endsWith("/") ? path.substring(0, path.length() - 1) : path;
    }

    /** {@code path} starts with {@code /internal/v1/...} and is built from code constants and {@link #segment} values only. */
    URI uri(String path) {
        return URI.create(origin + basePath + path);
    }

    /** Percent-encodes one path segment; a validated id is already all unreserved characters. */
    static String segment(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20");
    }

    static String requestId() {
        String current = MDC.get(MDC_REQUEST_ID);
        return AnalysisWire.validRequestId(current) ? current : UUID.randomUUID().toString();
    }

    Reply exchange(AiOperation operation, String method, URI uri, byte[] body, String idempotencyKey, Rejections rejections,
                   int... success) {
        String requestId = requestId();
        HttpRequest.Builder builder = HttpRequest.newBuilder(uri).timeout(settings.requestTimeout())
                .header("Authorization", authorization).header("Accept", "application/json")
                .header("X-Request-ID", requestId);
        if (idempotencyKey != null) {
            builder.header("Idempotency-Key", idempotencyKey);
        }
        if (body != null) {
            builder.header("Content-Type", "application/json");
            builder.method(method, HttpRequest.BodyPublishers.ofByteArray(body));
        } else {
            builder.method(method, HttpRequest.BodyPublishers.noBody());
        }
        HttpResponse<byte[]> response = send(builder.build(), operation, requestId);
        int status = response.statusCode();
        Optional<Duration> retryAfter = retryAfter(response);
        if (status >= 300 && status < 400) {
            throw transport(operation, requestId, Failure.REDIRECT_REFUSED, OptionalInt.of(status), null);
        }
        boolean expected = false;
        for (int candidate : success) {
            expected |= candidate == status;
        }
        try {
            requireJsonAnswer(response, requestId);
            JsonNode document = WireJson.parse(WireJson.utf8(response.body()), "body");
            if (expected) {
                return new Reply(status, document, retryAfter, requestId, operation);
            }
            if (status < 400) {
                throw transport(operation, requestId, Failure.UNEXPECTED_RESPONSE, OptionalInt.of(status), null);
            }
            throw rejections.decode(document, status, retryAfter, operation, requestId);
        } catch (Malformed error) {
            throw transport(operation, requestId, expected ? Failure.RESPONSE_MALFORMED : Failure.UNEXPECTED_RESPONSE,
                    OptionalInt.of(status), null);
        }
    }

    /** Runs a strict decoder over an accepted reply; any violation is a {@code RESPONSE_MALFORMED} transport failure. */
    static <T> T decode(Reply reply, Supplier<T> parser) {
        try {
            return parser.get();
        } catch (Malformed error) {
            throw transport(reply.operation(), reply.requestId(), Failure.RESPONSE_MALFORMED, OptionalInt.of(reply.status()), null);
        }
    }

    @Override
    public void close() {
        http.close();
    }

    private static void requireJsonAnswer(HttpResponse<byte[]> response, String requestId) {
        String type = response.headers().firstValue("Content-Type").orElse("");
        if (!JSON_MEDIA.matcher(type.strip()).matches()) {
            throw new Malformed("content-type");
        }
        if (!response.headers().firstValue("X-Request-ID").map(requestId::equals).orElse(false)) {
            throw new Malformed("x-request-id");
        }
    }

    private static Optional<Duration> retryAfter(HttpResponse<byte[]> response) {
        return response.headers().firstValue("Retry-After").map(String::strip).filter(v -> SECONDS.matcher(v).matches())
                .map(v -> Duration.ofSeconds(Long.parseLong(v)));
    }

    private HttpResponse<byte[]> send(HttpRequest request, AiOperation operation, String requestId) {
        int limit = settings.maxResponseBytes();
        CompletableFuture<HttpResponse<byte[]>> future = http.sendAsync(request, info ->
                new BoundedBodySubscriber(limit, info.headers().firstValueAsLong("Content-Length").orElse(-1)));
        try {
            return future.get(settings.requestTimeout().toMillis(), TimeUnit.MILLISECONDS);
        } catch (TimeoutException error) {
            future.cancel(true);
            throw transport(operation, requestId, Failure.TIMEOUT, OptionalInt.empty(), null);
        } catch (InterruptedException error) {
            future.cancel(true);
            Thread.currentThread().interrupt();
            throw transport(operation, requestId, Failure.INTERRUPTED, OptionalInt.empty(), null);
        } catch (ExecutionException error) {
            throw classify(operation, requestId, error.getCause());
        }
    }

    private static AiTransportException classify(AiOperation operation, String requestId, Throwable cause) {
        Throwable root = cause instanceof CompletionException && cause.getCause() != null ? cause.getCause() : cause;
        String type = root == null ? null : root.getClass().getSimpleName();
        Failure failure;
        if (root instanceof BoundedBodySubscriber.TooLarge) {
            failure = Failure.RESPONSE_TOO_LARGE;
        } else if (root instanceof HttpConnectTimeoutException) {
            failure = Failure.CONNECT_TIMEOUT;
        } else if (root instanceof HttpTimeoutException) {
            failure = Failure.TIMEOUT;
        } else if (root instanceof ConnectException) {
            failure = Failure.CONNECT_FAILED;
        } else {
            failure = Failure.IO_ERROR;
        }
        return transport(operation, requestId, failure, OptionalInt.empty(), type);
    }

    private static AiTransportException transport(AiOperation operation, String requestId, Failure failure, OptionalInt status,
                                                  String causeType) {
        return new AiTransportException(operation, requestId, failure, status, causeType);
    }
}
