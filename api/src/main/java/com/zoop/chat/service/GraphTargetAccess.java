package com.zoop.chat.service;

import com.zoop.common.exception.CustomException;
import com.zoop.graph.read.GraphContextLookup;
import com.zoop.graph.read.PublicGraphReader;
import java.time.Instant;
import java.util.LinkedHashSet;
import java.util.Optional;
import java.util.Set;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;

/**
 * {@link ChatTargetAccess} through the public graph read ({@link PublicGraphReader}: pinned version, asOf filter, current
 * exclusions), the same path the chat tools read targets through. A company id is visible as a company and an issue id as
 * an issue. No version, or a version, snapshot or database that cannot be read, is empty, never "all visible".
 */
@Component
public class GraphTargetAccess implements ChatTargetAccess {
    private final PublicGraphReader reader;

    public GraphTargetAccess(PublicGraphReader reader) {
        this.reader = reader;
    }

    @Override
    public Optional<Set<String>> visible(Set<String> ids, String graphVersion, Instant asOf, String requestId) {
        if (graphVersion == null) return Optional.empty();
        GraphContextLookup lookup;
        try {
            // The run's frozen pin, kept as it is: filtered only when the question was (#88), never a version-only address.
            lookup = new GraphContextLookup(reader.readPinned(graphVersion, asOf, asOf != null).graph());
        } catch (CustomException | DataAccessException | TransactionException unavailable) {
            return Optional.empty();
        }
        Set<String> visible = new LinkedHashSet<>();
        for (String id : ids) {
            lookup.find(id).filter(t -> "company".equals(t.kind()) || "issue".equals(t.kind()))
                    .ifPresent(t -> visible.add(id));
        }
        return Optional.of(Set.copyOf(visible));
    }
}
