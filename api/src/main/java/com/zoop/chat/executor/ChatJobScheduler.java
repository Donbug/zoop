package com.zoop.chat.executor;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.function.Supplier;

import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Drives {@link ChatJobExecutor} in the web application: claims queued jobs while a worker is free and runs each on its own
 * worker thread, and ends expired leases. With no {@link ChatEngine} registered it claims nothing. A run interrupted by a
 * shutdown keeps its lease until it expires and is then recovered like any other expired run.
 */
@Component
@ConditionalOnWebApplication
@ConditionalOnProperty(name = "zoop.chat.executor.enabled", havingValue = "true", matchIfMissing = true)
@EnableScheduling
public class ChatJobScheduler {
    private static final Logger log = LoggerFactory.getLogger(ChatJobScheduler.class);

    private final ChatJobExecutor executor;
    private final Semaphore free;
    private final ExecutorService workers;

    public ChatJobScheduler(ChatJobExecutor executor, @Value("${zoop.chat.executor.workers:2}") int workers) {
        if (workers < 1) throw new IllegalStateException("zoop.chat.executor.workers must be at least 1");
        this.executor = executor;
        this.free = new Semaphore(workers);
        this.workers = Executors.newFixedThreadPool(workers, Thread.ofPlatform().name("chat-run-", 1).factory());
    }

    @Scheduled(fixedDelayString = "PT0.5S", initialDelayString = "PT2S")
    public void claim() {
        while (free.tryAcquire()) {
            var claim = safely(executor::claimNext);
            if (claim == null || claim.isEmpty()) {
                free.release();
                return;
            }
            workers.execute(() -> {
                try {
                    executor.execute(claim.get());
                } catch (RuntimeException unexpected) {
                    log.warn("chat run of job {} stopped; its lease will be recovered", claim.get().job().id(), unexpected);
                } finally {
                    free.release();
                }
            });
        }
    }

    @Scheduled(fixedDelayString = "PT5S", initialDelayString = "PT5S")
    public void recover() {
        safely(executor::recoverExpired);
    }

    @PreDestroy
    void stop() {
        workers.shutdownNow();
    }

    private static <T> T safely(Supplier<T> work) {
        try {
            return work.get();
        } catch (RuntimeException unavailable) {
            log.warn("chat executor could not reach the job store", unavailable);
            return null;
        }
    }
}
