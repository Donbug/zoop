package com.zoop.briefing.market;

import java.io.IOException;
import java.net.URI;
import java.net.http.*;
import java.time.*;
import java.util.*;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.util.concurrent.*;

/** Small explicit read of existing keyless QuoteSourceOut providers. Never logs response bodies. */
public final class PublicMarketProvider {
    public enum Feed {
        KOSPI("yahoo","^KS11","https://query1.finance.yahoo.com/v8/finance/chart/%5EKS11?interval=1d&range=1mo"),
        KOSDAQ("yahoo","^KQ11","https://query1.finance.yahoo.com/v8/finance/chart/%5EKQ11?interval=1d&range=1mo"),
        FX("naver","FX_USDKRW","https://api.stock.naver.com/marketindex/exchange/FX_USDKRW"),
        FX_HISTORY("naver","FX_USDKRW","https://api.stock.naver.com/marketindex/exchange/FX_USDKRW/prices?pageSize=40&page=1");
        public final String provider,symbol,url;
        Feed(String provider,String symbol,String url) { this.provider=provider; this.symbol=symbol; this.url=url; }
    }
    public record Receipt(Feed feed,Instant collectedAt,int httpStatus,byte[] body,String failure) {
        public Receipt { body=body.clone(); Objects.requireNonNull(feed); Objects.requireNonNull(collectedAt); }
        @Override public byte[] body() { return body.clone(); }
        @Override public String toString() { return "MarketReceipt["+feed+","+httpStatus+","+failure+"]"; }
    }
    @FunctionalInterface public interface Transport { Receipt get(Feed feed) throws InterruptedException; }
    private PublicMarketProvider() {}
    public static Transport live(Clock clock) {
        var client=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(8)).followRedirects(HttpClient.Redirect.NEVER).build();
        return feed->fetch(client,URI.create(feed.url),feed,clock,Duration.ofSeconds(12));
    }
    static Receipt fetch(HttpClient client,URI uri,Feed feed,Clock clock,Duration timeout) throws InterruptedException {
            var request=HttpRequest.newBuilder(uri).timeout(timeout)
                .header("User-Agent","Zoop-development/0.1").header("Accept","application/json").GET().build();
            var pending=client.sendAsync(request,info->new LimitedBody());
            try {
                var response=pending.get(timeout.toMillis(),TimeUnit.MILLISECONDS);
                    String failure=response.statusCode()==200?null:response.statusCode()==401||response.statusCode()==403?"auth_failed":"temporary_failure";
                    return new Receipt(feed,clock.instant(),response.statusCode(),response.body(),failure);
            } catch (ExecutionException|TimeoutException e) {
                pending.cancel(true);
                Throwable cause=e;
                while(cause.getCause()!=null) cause=cause.getCause();
                return new Receipt(feed,clock.instant(),0,new byte[0],cause instanceof Oversize?"response_too_large":"temporary_failure");
            } catch(InterruptedException e) { pending.cancel(true); throw e; }
    }
    private static final class Oversize extends IOException {}
    private static final class LimitedBody implements HttpResponse.BodySubscriber<byte[]> {
        private final CompletableFuture<byte[]> result=new CompletableFuture<>();
        private final ByteArrayOutputStream buffer=new ByteArrayOutputStream();
        private Flow.Subscription subscription;
        @Override public CompletionStage<byte[]> getBody() { return result; }
        @Override public void onSubscribe(Flow.Subscription s) { subscription=s; s.request(1); }
        @Override public void onNext(List<ByteBuffer> chunks) {
            for(var chunk:chunks) {
                if((long)buffer.size()+chunk.remaining()>1_000_000) { subscription.cancel();result.completeExceptionally(new Oversize());return; }
                byte[] bytes=new byte[chunk.remaining()]; chunk.get(bytes); buffer.writeBytes(bytes);
            }
            subscription.request(1);
        }
        @Override public void onError(Throwable t) { result.completeExceptionally(t); }
        @Override public void onComplete() { result.complete(buffer.toByteArray()); }
    }
    public static List<Receipt> collect(Transport transport) throws InterruptedException {
        var receipts=new ArrayList<Receipt>();
        for(var feed:Feed.values()) receipts.add(transport.get(feed));
        return List.copyOf(receipts);
    }
}
