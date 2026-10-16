package com.zoop.briefing.market;

import com.sun.net.httpserver.HttpServer;
import java.net.*;
import java.net.http.HttpClient;
import java.time.*;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class PublicMarketProviderTest {
    @Test void httpErrorsAndOversizedBodiesAreBoundedFailureReceipts() throws Exception {
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/limited",x->{x.sendResponseHeaders(429,0);x.close();});
        server.createContext("/large",x->{byte[] b=new byte[1_000_001];x.sendResponseHeaders(200,b.length);try(var s=x.getResponseBody()){s.write(b);}catch(java.io.IOException ignored){};});
        server.start();
        try(var client=HttpClient.newHttpClient()) {
            String base="http://127.0.0.1:"+server.getAddress().getPort();
            var a=PublicMarketProvider.fetch(client,URI.create(base+"/limited"),PublicMarketProvider.Feed.FX,Clock.systemUTC(),Duration.ofSeconds(3));
            assertEquals(429,a.httpStatus()); assertEquals("temporary_failure",a.failure());
            var b=PublicMarketProvider.fetch(client,URI.create(base+"/large"),PublicMarketProvider.Feed.FX,Clock.systemUTC(),Duration.ofSeconds(3));
            assertEquals("response_too_large",b.failure()); assertEquals(0,b.body().length);
        } finally {server.stop(0);}
    }
    @Test void timeoutIncludesStalledResponseBodyRatherThanOnlyHeaders() throws Exception {
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        var executor=Executors.newVirtualThreadPerTaskExecutor();server.setExecutor(executor);
        server.createContext("/stall",x->{x.sendResponseHeaders(200,100);try(var body=x.getResponseBody()){body.write(1);body.flush();Thread.sleep(2000);}catch(Exception ignored){};});
        server.start();
        try(var client=HttpClient.newHttpClient()) {
            long start=System.nanoTime();
            var r=PublicMarketProvider.fetch(client,URI.create("http://127.0.0.1:"+server.getAddress().getPort()+"/stall"),
                PublicMarketProvider.Feed.FX,Clock.systemUTC(),Duration.ofMillis(250));
            assertEquals("temporary_failure",r.failure()); assertTrue(Duration.ofNanos(System.nanoTime()-start).toMillis()<1500);
        } finally {server.stop(0);executor.shutdownNow();}
    }
}
