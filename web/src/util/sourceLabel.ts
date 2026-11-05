/** API metadata.source는 내부 식별자다. 화면에는 사람이 읽을 이름으로 보이고, 모르는 값은 그대로 둔다. */
const LABELS: Record<string, string> = {
  public_graph_snapshot: 'ZOOP 관계 지도',
  'postgresql+public_graph_snapshot': 'ZOOP 관계 지도',
  'document-analysis': 'ZOOP 문서 분석',
};

export function sourceLabel(source: string) {
  return LABELS[source] ?? source;
}
