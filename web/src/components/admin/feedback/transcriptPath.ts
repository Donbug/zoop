// A-ADM-02b 대화록 상세 주소

/** 대화록 상세 주소. 열람 목적이 있으면 함께 넘겨 다시 묻지 않는다. */
export function transcriptPath(sessionId: string, purpose?: string | null) {
  const path = `/admin/feedback/transcripts/${encodeURIComponent(sessionId)}`;
  return purpose ? `${path}?purpose=${encodeURIComponent(purpose)}` : path;
}
