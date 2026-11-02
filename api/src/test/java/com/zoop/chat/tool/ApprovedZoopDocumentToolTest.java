package com.zoop.chat.tool;

import static org.junit.jupiter.api.Assertions.*;

import com.zoop.chat.service.ChatZoopDocs;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;

/** Q01 approved help and screen documents: fixed targets, citable sections and a fail-closed startup gate. */
class ApprovedZoopDocumentToolTest {
    private static final Instant NOW = Instant.parse("2026-11-01T00:00:00Z");

    @Test
    void helpAndScreenReadsUseOnlyTheirOwnFixedApprovedDocument() {
        var docs = docs(true);
        var help = new HelpSearchTool(docs);
        var screen = new ScreenSpecReadTool(docs);
        help.afterPropertiesSet();
        screen.afterPropertiesSet();

        var scope = new ChatToolScope("job-1", null, NOW);
        var helpOut = help.read(scope, new ChatToolRequest(help.capability().id(),
                List.of(ChatZoopDocs.HELP_GUIDE, ChatZoopDocs.SCREEN_GUIDE), 20));
        var screenOut = screen.read(scope, new ChatToolRequest(screen.capability().id(),
                List.of(ChatZoopDocs.SCREEN_GUIDE, ChatZoopDocs.HELP_GUIDE), 20));

        assertEquals(ChatCapability.HELP_SEARCH, help.capability());
        assertEquals(List.of(ChatZoopDocs.HELP_GUIDE), helpOut.items().stream().map(ChatToolItem::id).toList());
        assertEquals(List.of("ev-help"), helpOut.evidenceIds());
        assertEquals(ChatCapability.SCREEN_SPEC_READ, screen.capability());
        assertEquals(List.of(ChatZoopDocs.SCREEN_GUIDE), screenOut.items().stream().map(ChatToolItem::id).toList());
        assertEquals(List.of("ev-screen"), screenOut.evidenceIds());
    }

    @Test
    void enablingEitherBindingWithoutItsApprovedDocumentFailsStartup() {
        var docs = docs(false);

        assertThrows(IllegalStateException.class, () -> new HelpSearchTool(docs).afterPropertiesSet());
        assertThrows(IllegalStateException.class, () -> new ScreenSpecReadTool(docs).afterPropertiesSet());
    }

    @Test
    void enablingABindingRejectsDocumentsOutsideTheModelQuoteContract() {
        assertThrows(IllegalStateException.class,
                () -> new HelpSearchTool(docsWithQuotes(ChatToolRequest.MAX_LIMIT + 1, 10)).afterPropertiesSet());
        assertThrows(IllegalStateException.class,
                () -> new HelpSearchTool(docsWithQuotes(1, 2_001)).afterPropertiesSet());
    }

    @Test
    void aLaterInvalidApprovedVersionIsRejectedAtReadTimeInsteadOfBeingTruncated() {
        var help = new HelpSearchTool(docsWithQuotes(ChatToolRequest.MAX_LIMIT + 1, 10));
        var request = new ChatToolRequest(help.capability().id(), List.of(ChatZoopDocs.HELP_GUIDE), 20);

        assertThrows(ChatToolUnavailable.class, () -> help.read(new ChatToolScope("job-1", null, NOW), request));
    }

    @Test
    void bindingsAreOffByDefaultAndEnabledOnlyWhenApprovedDocumentsAreReady() {
        var runner = new ApplicationContextRunner().withUserConfiguration(Bindings.class)
                .withBean(ChatZoopDocs.class, () -> docs(true));
        runner.run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(HelpSearchTool.class).isEmpty());
            assertTrue(context.getBeansOfType(ScreenSpecReadTool.class).isEmpty());
        });
        runner.withPropertyValues("zoop.chat.approved-docs.enabled=true").run(context -> {
            assertNull(context.getStartupFailure());
            assertNotNull(context.getBean(HelpSearchTool.class));
            assertNotNull(context.getBean(ScreenSpecReadTool.class));
        });
    }

    @Test
    void enabledBindingsFailTheApplicationContextClosedWithoutApprovedDocuments() {
        new ApplicationContextRunner().withUserConfiguration(Bindings.class)
                .withBean(ChatZoopDocs.class, () -> docs(false))
                .withPropertyValues("zoop.chat.approved-docs.enabled=true")
                .run(context -> assertNotNull(context.getStartupFailure()));
    }

    private static ChatZoopDocs docs(boolean available) {
        return new ChatZoopDocs(null, Clock.fixed(NOW, ZoneOffset.UTC)) {
            @Override
            public Optional<Document> inEffect(String docId, Instant asOf) {
                if (!available) return Optional.empty();
                return switch (docId) {
                    case HELP_GUIDE -> Optional.of(document(docId, "서비스 이용 안내", "ev-help"));
                    case SCREEN_GUIDE -> Optional.of(document(docId, "화면 설명", "ev-screen"));
                    default -> Optional.empty();
                };
            }
        };
    }

    private static ChatZoopDocs.Document document(String id, String title, String evidenceId) {
        return new ChatZoopDocs.Document(id, "2026-11-01.1", title,
                List.of(new ChatZoopDocs.Quote(evidenceId, id, "2026-11-01.1", title + " · 안내",
                        "## 안내\n\n승인된 설명", 0, 12)));
    }

    private static ChatZoopDocs docsWithQuotes(int count, int textLength) {
        return new ChatZoopDocs(null, Clock.fixed(NOW, ZoneOffset.UTC)) {
            @Override
            public Optional<Document> inEffect(String docId, Instant asOf) {
                var quotes = java.util.stream.IntStream.range(0, count)
                        .mapToObj(i -> new Quote("ev-" + i, docId, "2026-11-01.1", "section " + i,
                                "x".repeat(textLength), 0, textLength))
                        .toList();
                return Optional.of(new Document(docId, "2026-11-01.1", "guide", quotes));
            }
        };
    }

    @Configuration(proxyBeanMethods = false)
    @Import({HelpSearchTool.class, ScreenSpecReadTool.class})
    static class Bindings { }
}
