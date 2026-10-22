package com.zoop.ai.http;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.Optional;
import java.util.regex.Pattern;

import com.zoop.ai.AiClientException;
import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.AiServiceErrorException;
import com.zoop.ai.chat.ChatStageCall;
import com.zoop.ai.chat.ChatStageClient;
import com.zoop.ai.chat.ChatStageReply;
import com.zoop.ai.http.AiHttpTransport.Reply;
import com.zoop.ai.http.WireJson.Malformed;
import com.zoop.ai.http.WireJson.Obj;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.JsonNodeFactory;
import tools.jackson.databind.node.ObjectNode;

/**
 * {@link ChatStageClient} over the shared {@link AiHttpTransport}. The answer must be a {@code zoop-ai-chat-1} result for the
 * same invocation and stage; anything else is a {@code RESPONSE_MALFORMED} transport failure, which for this mutating operation
 * means the stage may have sent a request. Error envelopes are the S1 family's ({@code zoop-ai-internal-1}).
 */
public final class HttpChatStageClient implements ChatStageClient, AutoCloseable {
    static final String SCHEMA = "zoop-ai-chat-1";
    private static final String PATH = "/internal/v1/chat-stages/";
    private static final Pattern FAILURE_CODE = Pattern.compile("[a-z0-9_]{1,64}");
    private static final Pattern NAME = Pattern.compile("[\\x20-\\x7E]{1,200}");

    private final AiHttpTransport transport;

    public HttpChatStageClient(AiClientSettings settings) {
        this.transport = new AiHttpTransport(settings);
    }

    @Override
    public ChatStageReply invoke(ChatStageCall call) {
        ObjectNode body = JsonNodeFactory.instance.objectNode();
        body.put("schemaVersion", SCHEMA).put("invocationId", call.invocationId()).put("stage", call.stage())
                .put("mode", call.mode()).set("input", call.input());
        Reply reply = transport.exchange(AiOperation.CHAT_STAGE, "POST",
                transport.uri(PATH + AiHttpTransport.segment(call.stage())),
                WireJson.compact(body).getBytes(StandardCharsets.UTF_8), call.invocationId(),
                HttpChatStageClient::rejection, 200);
        return AiHttpTransport.decode(reply, () -> decode(reply.body(), call));
    }

    static ChatStageReply decode(JsonNode node, ChatStageCall call) {
        Obj root = Obj.of(node, "body");
        if (!SCHEMA.equals(root.string("schemaVersion", NAME)) || !call.invocationId().equals(root.string("invocationId", NAME))
                || !call.stage().equals(root.string("stage", NAME))) {
            throw new Malformed("identity");
        }
        String status = root.string("status", NAME);
        boolean succeeded;
        if ("succeeded".equals(status)) succeeded = true;
        else if ("failed".equals(status)) succeeded = false;
        else throw new Malformed("status");
        JsonNode answer = root.raw("answer");
        ChatStageReply.Failure failure = root.optObject("failure").map(f -> new ChatStageReply.Failure(
                f.string("code", FAILURE_CODE), f.bool("sent"), f.bool("unknown"))).orElse(null);
        if (succeeded ? (answer == null || !answer.isObject() || failure != null) : (failure == null)) {
            throw new Malformed("outcome");
        }
        ChatStageReply.Receipt receipt = root.optObject("receipt").map(HttpChatStageClient::receipt).orElse(null);
        return new ChatStageReply(call.invocationId(), call.stage(), succeeded, succeeded ? answer : null, failure, receipt);
    }

    private static ChatStageReply.Receipt receipt(Obj r) {
        Obj usage = r.object("usage");
        return new ChatStageReply.Receipt(r.string("provider", NAME), r.string("providerRevision", NAME),
                r.string("model", NAME), r.string("promptVersion", NAME), r.string("executionMode", NAME),
                usage.optCount("inputTokens"), usage.optCount("outputTokens"), instant(r.string("sentAt", NAME)),
                r.optString("receivedAt", NAME).map(HttpChatStageClient::instant).orElse(null));
    }

    private static Instant instant(String value) {
        try {
            return java.time.OffsetDateTime.parse(value).toInstant();
        } catch (DateTimeParseException error) {
            throw new Malformed("time");
        }
    }

    private static AiClientException rejection(JsonNode document, int status, Optional<Duration> retryAfter, AiOperation operation,
            String requestId) {
        AnalysisWire.Rejection rejection = AnalysisWire.rejection(document, null, retryAfter);
        if (!rejection.requestId().equals(requestId)) {
            throw new Malformed("error.requestId");
        }
        return new AiServiceErrorException(operation, requestId, status, rejection.code(), rejection.retryable(),
                rejection.runtimeCode(), rejection.field(), retryAfter, Optional.empty());
    }

    @Override
    public void close() {
        transport.close();
    }
}
