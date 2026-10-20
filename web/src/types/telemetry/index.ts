// FS065 사용 이벤트 (docs/api/openapi.yaml TelemetryEvent)
// 허용된 필드만 있다. 이름·이메일·입력한 글을 담을 칸은 없다.

export type TelemetryEvent =
  | { type: 'screen_view'; screen: 'main' | 'briefing'; viewId: string }
  | {
      type: 'graph_node_select' | 'graph_edge_select';
      targetId: string;
      viewId?: string;
    }
  | { type: 'briefing_view'; targetId: string; viewId?: string }
  | {
      type: 'briefing_issue_open';
      targetId: string;
      roundId: string;
      viewId?: string;
    };
