// FS066-01 AI 결과 평가 (docs/api/openapi.yaml FeedbackVote·FeedbackItem·FeedbackList)
// 한 사람이 결과마다 평가 하나다. 원하는 최종 상태(up·down·none)를 보내므로 다시 보내도 토글되지 않는다.

export type FeedbackFeature =
  'chatbot_answer' | 'news_summary' | 'briefing_round' | 'briefing_issue';

export type FeedbackValue = 'up' | 'down' | 'none';

export type FeedbackVote = {
  feature: FeedbackFeature;
  targetId: string;
  value: FeedbackValue;
  /** 사용자가 본 결과 버전(브리핑은 feedbackVersion (구버전은 graphVersion)). 서버의 현재 버전과 다르면 409 */
  targetVersion?: string | null;
  /** 싫어요에만 붙이는 선택 사유 */
  reason?: string | null;
};

export type FeedbackItem = {
  feature: FeedbackFeature;
  targetId: string;
  targetVersion: string | null;
  value: FeedbackValue;
  reason: string | null;
};

export type FeedbackList = {
  items: FeedbackItem[];
  nextCursor: string | null;
};
