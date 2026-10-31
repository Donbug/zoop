import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/apis/auth/ApiService';
import { getEvidence } from '@/apis/evidence/evidence';
import EvidenceDrawer from '@/components/evidence/EvidenceDrawer';
import { createMockEvidence } from '@/mocks/evidence/fixture';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import { useTutorialInteractionLock } from '@/components/graph/tutorial/useTutorialInteractionLock';

vi.mock('@/apis/evidence/evidence', async (original) => ({
  ...(await original<typeof import('@/apis/evidence/evidence')>()),
  getEvidence: vi.fn(),
}));

const mocked = vi.mocked(getEvidence);
const target = {
  kind: 'issue' as const,
  id: 'mock-issue-1',
  label: 'HBM4 공급 계약',
  evidenceIds: ['mock-evidence-1', 'mock-evidence-1-detail'],
  mapContext: {
    url: '/?select=node%3Amock-issue-1',
    graphVersion: 'mock-graph-v1',
    asOf: '2026-10-06T03:41:00Z',
  },
};

function Harness({
  onViewOnMap = vi.fn(),
  result = 'edges',
}: {
  onViewOnMap?: (selection: unknown) => void;
  result?: 'edges' | 'event' | 'none';
}) {
  // 지도 쪽 결과를 흉내 낸다: 고른 근거가 있으면 result, 없으면 null.
  const [mapResult, setMapResult] = useState<typeof result | null>(null);
  return (
    <>
      <button onClick={() => useGraphUiStore.getState().openEvidence(target)}>
        근거 열기
      </button>
      <EvidenceDrawer
        mapResult={mapResult}
        onViewOnMap={(selection) => {
          onViewOnMap(selection);
          setMapResult(selection ? result : null);
        }}
      />
    </>
  );
}

beforeEach(() => {
  mocked.mockReset();
  useGraphUiStore.getState().reset();
});

describe('D-GRP-05 · evidence drawer states and interactions', () => {
  it('traps reverse Tab from the heading and restores background interaction on close', async () => {
    mocked.mockImplementation(async (id) => createMockEvidence(id));
    render(<Harness />);
    const opener = screen.getByRole('button', { name: '근거 열기' });
    await userEvent.click(opener);
    await screen.findByText('[가상 공시] HBM4 공급 계약 참고 자료');
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole('heading', { name: '근거 문서' }),
      ),
    );
    expect(opener.inert).toBe(true);
    await userEvent.tab({ shift: true });
    expect(document.activeElement).toBe(
      screen.getAllByRole('button', { name: '◇ 지도에서 보기' }).at(-1),
    );
    await userEvent.keyboard('{Escape}');
    expect(opener.inert).not.toBe(true);
    expect(document.activeElement).toBe(opener);
  });
  it('D-GRP-05 15번 강조 중에는 지도를 어둡게 덮지 않고, 지도에 없으면 알리고 눌린 상태로 두지 않는다', async () => {
    mocked.mockImplementation(async (id) => createMockEvidence(id));
    const view = render(<Harness result="none" />);
    await userEvent.click(screen.getByRole('button', { name: '근거 열기' }));
    await screen.findByRole('dialog', { name: '근거 문서' });
    const [first] = screen.getAllByRole('button', { name: '◇ 지도에서 보기' });
    await userEvent.click(first);
    expect(screen.getByRole('status').textContent).toContain(
      '이 근거와 연결된 선이나 사건이 지금 지도에 없어요.',
    );
    expect(first.getAttribute('aria-pressed')).toBe('false');
    expect(view.container.querySelector('[class~="bg-black/35"]')).toBeTruthy();
    view.unmount();
    useGraphUiStore.getState().closeEvidence();

    render(<Harness result="edges" />);
    await userEvent.click(screen.getByRole('button', { name: '근거 열기' }));
    await screen.findByRole('dialog', { name: '근거 문서' });
    await userEvent.click(
      screen.getAllByRole('button', { name: '◇ 지도에서 보기' })[0],
    );
    expect(document.querySelector('[class~="bg-black/35"]')).toBeNull();
    expect(screen.queryByText(/지금 지도에 없어요/)).toBeNull();
  });

  it('shows source, publication time, captured quotes and link availability', async () => {
    mocked.mockImplementation(async (id) => createMockEvidence(id));
    const onViewOnMap = vi.fn();
    render(<Harness onViewOnMap={onViewOnMap} />);
    await userEvent.click(screen.getByRole('button', { name: '근거 열기' }));
    const dialog = await screen.findByRole('dialog', { name: '근거 문서' });
    expect(dialog.getAttribute('data-screen-id')).toBe('D-GRP-05');
    expect(screen.getByText('HBM4 공급 계약')).toBeTruthy();
    expect(screen.getByText(/관계 확인 시점 확인 시점 미제공/)).toBeTruthy();
    expect(screen.getByText(/줍 가상 뉴스룸 \(example.com\)/)).toBeTruthy();
    expect(screen.getByText('발행 2026-10-06 09:00 KST')).toBeTruthy();
    expect(screen.getAllByText(/합성 인용문|추가로 확인/)).toHaveLength(2);
    expect(
      screen
        .getByRole('link', {
          name: '↗ 원문 기사 보기 (새 창에서 열림)',
        })
        .getAttribute('href'),
    ).toBe('https://example.com/zoop/mock-issue-1');
    expect(screen.getByText('원문 링크가 제공되지 않았습니다.')).toBeTruthy();
    const mapButtons = screen.getAllByRole('button', {
      name: '◇ 지도에서 보기',
    });
    await userEvent.click(mapButtons[0]);
    expect(onViewOnMap).toHaveBeenCalledWith({
      evidenceId: 'mock-evidence-1',
      eventIds: ['mock-issue-1'],
    });
    expect(mapButtons[0].getAttribute('aria-pressed')).toBe('true');
    await userEvent.click(mapButtons[0]);
    expect(onViewOnMap).toHaveBeenLastCalledWith(null);
    expect(mapButtons[0].getAttribute('aria-pressed')).toBe('false');
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(
      screen.getByRole('button', { name: '근거 열기' }),
    );
  });

  it('announces loading while evidence reads are pending', async () => {
    mocked.mockImplementation(() => new Promise(() => {}));
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: '근거 열기' }));
    expect(screen.getByRole('status').textContent).toContain('불러오는 중');
  });

  it('renders empty evidence without pretending it is a request failure', async () => {
    render(<EvidenceDrawer />);
    useGraphUiStore.getState().openEvidence({
      kind: 'issue',
      id: 'empty',
      evidenceIds: [],
    });
    expect(await screen.findByText('연결된 근거가 없습니다.')).toBeTruthy();
    expect(screen.getByText(/근거가 충분하지 않아/)).toBeTruthy();
    expect(mocked).not.toHaveBeenCalled();
  });

  it('distinguishes permission, unavailable and retryable partial failures', async () => {
    mocked.mockImplementation(async (id) => {
      if (id === 'mock-evidence-1') return createMockEvidence(id);
      throw new ApiError(
        503,
        'SOURCE_UNAVAILABLE',
        '근거 저장소에 연결할 수 없습니다.',
      );
    });
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: '근거 열기' }));
    expect(
      await screen.findByText('일부 근거를 불러오지 못했습니다.'),
    ).toBeTruthy();
    expect(screen.getByText(/조회 실패 · 근거 저장소/)).toBeTruthy();
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy();

    mocked.mockReset();
    mocked
      .mockRejectedValueOnce(
        new ApiError(403, 'ACCESS_DENIED', '권한이 없습니다.'),
      )
      .mockRejectedValueOnce(
        new ApiError(404, 'EVIDENCE_UNAVAILABLE', '비공개입니다.'),
      );
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText(/권한 없음/)).toBeTruthy();
    expect(screen.getByText(/제공 불가/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull();
  });

  it('recovers from failure and restores focus when closed', async () => {
    mocked
      .mockRejectedValueOnce(
        new ApiError(503, 'SOURCE_UNAVAILABLE', '일시적인 오류'),
      )
      .mockRejectedValueOnce(
        new ApiError(503, 'SOURCE_UNAVAILABLE', '일시적인 오류'),
      )
      .mockImplementation(async (id) => createMockEvidence(id));
    render(<Harness />);
    const opener = screen.getByRole('button', { name: '근거 열기' });
    await userEvent.click(opener);
    await screen.findByText('근거를 불러오지 못했습니다.');
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await screen.findByText(/합성 인용문/);
    await userEvent.click(screen.getByRole('button', { name: '근거 창 닫기' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });

  it('D-GRP-T4 튜토리얼 4단계에서 근거를 불러오지 못해도 닫기 버튼으로 창을 닫고 다음 단계로 이어 간다', async () => {
    mocked.mockImplementation(async (id) => ({
      ...createMockEvidence(id),
      article: null,
    }));
    const onClosed = vi.fn();
    function Step4() {
      useTutorialInteractionLock(4, false);
      return <EvidenceDrawer onClosed={onClosed} />;
    }
    useGraphUiStore.getState().openEvidence(target);
    render(<Step4 />);
    await screen.findAllByText('근거 문서를 제공할 수 없습니다.');
    const close = screen.getByRole('button', {
      name: '근거 창 닫기',
    }) as HTMLButtonElement;
    await waitFor(() => expect(close.disabled).toBe(false));
    await userEvent.click(close);
    expect(onClosed).toHaveBeenCalledOnce();
    expect(useGraphUiStore.getState().evidenceTarget ?? null).toBeNull();
  });
});
