package com.zoop.graph.rules;

/** A stored rule definition the app cannot read exactly; {@code getMessage()} names the part (never a stored value). */
public final class InvalidRuleDefinitionException extends RuntimeException {
    public InvalidRuleDefinitionException(String part) {
        super(part, null, false, false);
    }
}
