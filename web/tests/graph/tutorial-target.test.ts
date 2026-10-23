import { describe, expect, it } from 'vitest';
import { tutorialTarget } from '@/components/graph/tutorial/tutorial-target';
import { createMockGraph } from '@/mocks/graph/response';

describe('FS015 실제 그래프 안내 대상', () => {
  it('개인 지도에서는 보유·관심 기업과 실제 연결된 사건을 선택한다', () => {
    const graph = createMockGraph({ mode: 'personal', personalFilter: 'all' });
    const target = tutorialTarget(graph, false)!;
    expect(target.company.holding || target.company.watch).toBe(true);
    expect(
      graph.edges.some(
        (edge) =>
          [edge.source, edge.target].includes(target.company.id) &&
          [edge.source, edge.target].includes(target.issue.id),
      ),
    ).toBe(true);
  });
  it('대체 지도에서는 삼성전자만 사용하고 없으면 임의 기업/사건을 만들지 않는다', () => {
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    expect(tutorialTarget(graph, true)?.company.id).toBe('KRX:005930');
    graph.nodes = graph.nodes.filter((node) => node.id !== 'KRX:005930');
    expect(tutorialTarget(graph, true)).toBeNull();
  });
  it('사건 공유 파생 선과 끊어진 연결은 실습 경로로 사용하지 않는다', () => {
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    graph.edges = graph.edges.filter((edge) => edge.derived);
    expect(tutorialTarget(graph, false)).toBeNull();
    expect(tutorialTarget(null, false)).toBeNull();
  });
});
