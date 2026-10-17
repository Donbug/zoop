package com.zoop.graph.version;

/**
 * A version id is already registered with a different snapshot. Registered history is immutable, so this is refused
 * rather than overwritten. Not a {@link org.springframework.dao.DataAccessException}: it is a domain decision.
 */
public class GraphVersionConflictException extends RuntimeException {
    public GraphVersionConflictException(String versionId) {
        super("Graph version " + versionId + " is already registered with another snapshot");
    }
}
