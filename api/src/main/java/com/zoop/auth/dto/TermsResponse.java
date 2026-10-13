package com.zoop.auth.dto;

import java.util.List;

public record TermsResponse(List<TermOut> items, String nextCursor) {
}
