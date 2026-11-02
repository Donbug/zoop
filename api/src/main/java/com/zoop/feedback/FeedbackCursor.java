package com.zoop.feedback;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.auth.service.SignedCursor;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.time.Instant;
import tools.jackson.databind.ObjectMapper;

final class FeedbackCursor {
  record Position(
      String keyId,
      String owner,
      String filters,
      int limit,
      Instant asOf,
      String first,
      String last)
      implements SignedCursor.Position {}

  static Position decode(
      ObjectMapper mapper,
      CsrfKeyRing keys,
      String purpose,
      String cursor,
      String owner,
      String filters,
      Integer limit) {
    try {
      var p = SignedCursor.decode(mapper, keys, purpose, cursor, Position.class);
      if (p != null
          && (!owner.equals(p.owner())
              || !filters.equals(p.filters())
              || p.limit() < 1
              || p.limit() > 100
              || limit != null && limit != p.limit()
              || p.asOf() == null
              || p.first() == null
              || p.last() == null)) throw new IllegalArgumentException();
      return p;
    } catch (RuntimeException error) {
      throw new CustomException(ErrorCode.INVALID_CURSOR, error);
    }
  }

  static String encode(
      ObjectMapper mapper,
      CsrfKeyRing keys,
      String purpose,
      String owner,
      String filters,
      int limit,
      Instant asOf,
      String first,
      String last) {
    return SignedCursor.encode(
        mapper,
        keys,
        purpose,
        new Position(keys.activeKeyId(), owner, filters, limit, asOf, first, last));
  }
}
