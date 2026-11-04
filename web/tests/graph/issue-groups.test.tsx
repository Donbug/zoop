import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import IsolatedIssuesPanel from '@/components/graph/IsolatedIssuesPanel';
import { groupIssues } from '@/components/graph/issue-groups';
import { toG6Data } from '@/components/graph/graph-model';
import type { GraphEdge, GraphNode, GraphResponse } from '@/types/map/graph';

// D-GRP-01: 같은 제목(기사 제목)의 서로 다른 사건을 지도 노드 하나로 묶는다. 합성 fixture.

function node(id: string, overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id,
    kind: 'issue',
    label: '삼성, 미래 성장 위해 호남에 425조원 투자',
    isFocus: false,
    holding: false,
    watch: false,
    brandColor: null,
    logoUrl: null,
    eventTime: null,
    timePrecision: null,
    action: null,
    target: null,
    evidenceCount: 1,
    geography: 'domestic',
    ...overrides,
  };
}

function edge(
  id: string,
  source: string,
  target: string,
  overrides: Partial<GraphEdge> = {},
): GraphEdge {
  return {
    id,
    source,
    target,
    relationType: 'INVOLVES',
    role: null,
    summary: '직접 관련',
    assertionStatus: 'occurred',
    derived: false,
    via: [],
    evidenceIds: [`ev-${id}`],
    ...overrides,
  };
}

const company = (id: string, label: string): GraphNode =>
  node(id, { kind: 'company', label, evidenceCount: null, geography: null });

function graph(): GraphResponse {
  return {
    nodes: [
      company('KRX:005930', '삼성전자'),
      company('KRX:028260', '삼성물산'),
      node('issue-b', {
        target: '광주 신규 반도체 Fab 2개 건설',
        action: '투자 계획',
        eventTime: '2026-10-02',
        evidenceCount: 1,
      }),
      node('issue-a', {
        target: '무탄소 미래 에너지 투자',
        action: '투자할 방침',
        evidenceCount: 2,
      }),
      node('issue-c', { label: '삼성전자, 갤럭시 워치 건강 관리 기능 추가' }),
    ],
    edges: [
      edge('e1', 'issue-b', 'KRX:005930'),
      edge('e2', 'issue-a', 'KRX:028260'),
      edge('e3', 'issue-a', 'KRX:005930'),
      edge('e4', 'issue-c', 'KRX:005930'),
      edge('e5', 'KRX:005930', 'KRX:028260', {
        relationType: 'SHARES_ISSUE',
        via: ['issue-a', 'issue-b'],
      }),
    ],
    metadata: {} as GraphResponse['metadata'],
  };
}

it('D-GRP-01 같은 제목 사건을 노드 하나로 묶고 기업 연결은 합친다', () => {
  const { graph: view, members, groupOf, edgeOf } = groupIssues(graph());
  const issues = view.nodes.filter((item) => item.kind === 'issue');
  expect(issues.map((item) => item.id)).toEqual(['group:issue-a', 'issue-c']);
  const group = issues[0];
  expect(group.label).toBe('삼성, 미래 성장 위해 호남에 425조원 투자');
  expect(group.evidenceCount).toBe(3);
  // 시각을 아는 사건이 먼저, 원래 사건 ID는 그대로 남는다.
  expect(members.get('group:issue-a')?.map((item) => item.id)).toEqual([
    'issue-b',
    'issue-a',
  ]);
  expect(groupOf.get('issue-b')).toBe('group:issue-a');
  expect(groupOf.has('issue-c')).toBe(false);

  const involves = view.edges.filter(
    (item) => item.relationType === 'INVOLVES',
  );
  // 삼성전자로 가는 두 선(e1·e3)은 하나로 합치고 근거는 모두 남긴다.
  expect(
    involves
      .filter((item) => item.source === 'group:issue-a')
      .map((item) => [item.id, item.target, item.evidenceIds]),
  ).toEqual([
    ['e1', 'KRX:005930', ['ev-e1', 'ev-e3']],
    ['e2', 'KRX:028260', ['ev-e2']],
  ]);
  expect(edgeOf.get('e3')).toBe('e1');
  expect(
    view.edges.find((item) => item.relationType === 'SHARES_ISSUE')?.via,
  ).toEqual(['group:issue-a']);
  // 그리기 모델도 묶음 노드 하나만 만든다.
  const g6 = toG6Data(view);
  expect(g6.nodes?.filter((item) => item.id.startsWith('group:'))).toHaveLength(
    1,
  );
});

it('D-GRP-01 같은 제목이 없으면 그래프를 그대로 쓴다', () => {
  const source = graph();
  source.nodes = source.nodes.filter((item) => item.id !== 'issue-a');
  const result = groupIssues(source);
  expect(result.graph).toBe(source);
  expect(result.members.size).toBe(0);
});

it('D-GRP-01 묶음 패널은 묶인 사건을 내용으로 구분해 보여 주고 원래 사건을 연다', async () => {
  const { members } = groupIssues(graph());
  const issues = members.get('group:issue-a')!;
  const select = vi.fn();
  render(
    <IsolatedIssuesPanel
      issues={issues}
      title={issues[0].label}
      description={`같은 제목으로 묶인 사건 ${issues.length}건이에요.`}
      closeLabel="묶인 사건 닫기"
      searchable={false}
      rowLabel={(issue) =>
        [issue.target, issue.action].filter(Boolean).join(' · ')
      }
      onSelect={select}
      onClose={vi.fn()}
    />,
  );
  expect(
    screen.getByRole('heading', {
      name: '삼성, 미래 성장 위해 호남에 425조원 투자',
    }),
  ).toBeTruthy();
  expect(screen.queryByLabelText('사건 검색')).toBeNull();
  expect(screen.getByRole('button', { name: '묶인 사건 닫기' })).toBeTruthy();
  await userEvent.click(
    screen.getByRole('button', {
      name: '무탄소 미래 에너지 투자 · 투자할 방침',
    }),
  );
  expect(select).toHaveBeenCalledWith('issue-a');
});
