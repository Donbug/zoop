package com.zoop.ai.http;

import java.io.ByteArrayOutputStream;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.Flow;

/** Collects a response body but stops reading, and fails, as soon as it exceeds the limit (declared or actual). */
final class BoundedBodySubscriber implements HttpResponse.BodySubscriber<byte[]> {

    static final class TooLarge extends RuntimeException {
        TooLarge() {
            super("response too large", null, false, false);
        }
    }

    private final CompletableFuture<byte[]> body = new CompletableFuture<>();
    private final ByteArrayOutputStream buffer = new ByteArrayOutputStream();
    private final int limit;
    private final long declaredLength;
    private Flow.Subscription subscription;

    BoundedBodySubscriber(int limit, long declaredLength) {
        this.limit = limit;
        this.declaredLength = declaredLength;
    }

    @Override
    public CompletionStage<byte[]> getBody() {
        return body;
    }

    @Override
    public void onSubscribe(Flow.Subscription subscription) {
        this.subscription = subscription;
        if (declaredLength > limit) {
            subscription.cancel();
            body.completeExceptionally(new TooLarge());
            return;
        }
        subscription.request(Long.MAX_VALUE);
    }

    @Override
    public void onNext(List<ByteBuffer> items) {
        if (body.isDone()) {
            return;
        }
        for (ByteBuffer item : items) {
            if ((long) buffer.size() + item.remaining() > limit) {
                subscription.cancel();
                body.completeExceptionally(new TooLarge());
                return;
            }
            byte[] chunk = new byte[item.remaining()];
            item.get(chunk);
            buffer.writeBytes(chunk);
        }
    }

    @Override
    public void onError(Throwable error) {
        body.completeExceptionally(error);
    }

    @Override
    public void onComplete() {
        body.complete(buffer.toByteArray());
    }
}
