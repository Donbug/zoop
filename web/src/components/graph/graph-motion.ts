/**
 * D-GRP-01 지도 카메라·배치 움직임. 값은 index.css의 --motion-* 토큰과 같다(프로토타입 tokens.css).
 * 동작 줄이기를 켰거나 matchMedia가 없으면(테스트 환경) 지금처럼 바로 옮긴다.
 * 매번 다시 읽으므로 사용자가 설정을 바꾸면 다음 이동부터 따른다.
 */
export type CameraMove = 'select' | 'zoom' | 'fit' | 'layout';

const DURATION: Record<CameraMove, number> = {
  select: 300,
  zoom: 250,
  fit: 300,
  // 포커스 진입·단계 바꾸기·전체 보기에서 노드가 새 자리로 옮겨 가는 시간.
  // 프로토타입 graph-layout은 600ms지만, 노드 500개에서 프레임마다 다시 그리는 비용이 커서 절반으로 줄였다.
  layout: 300,
};
const STANDARD_EASING = 'cubic-bezier(0.35, 0, 0.35, 1)';

export function cameraMotion(
  move: CameraMove,
): false | { duration: number; easing: string } {
  if (
    typeof window.matchMedia !== 'function' ||
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
    return false;
  return { duration: DURATION[move], easing: STANDARD_EASING };
}

/**
 * 노드·연결선은 평소에 바로 그린다. 배치를 바꿀 때 translateElementTo(…, true)로 부른 이동만 움직인다.
 * G6 5의 요소 애니메이션은 호출마다 길이를 받지 못하므로 여기에 둔다.
 */
const STILL = {
  enter: false,
  exit: false,
  show: false,
  hide: false,
  update: false,
} as const;
export const NODE_ANIMATION = {
  ...STILL,
  translate: [
    { fields: ['x', 'y'], duration: DURATION.layout, easing: STANDARD_EASING },
  ],
};
export const EDGE_ANIMATION = {
  ...STILL,
  translate: [
    {
      fields: ['sourceNode', 'targetNode'],
      duration: DURATION.layout,
      easing: STANDARD_EASING,
    },
  ],
};

type RoundLogoGraph = {
  context?: {
    element?: {
      getElement(
        id: string,
      ):
        | { getShape(key: string): { children?: unknown[] } | undefined }
        | undefined;
    };
  };
};

/**
 * G6 5.1.1은 둥글게 자른 로고(iconRadius)의 잘라내기 영역을 절대 좌표로 둔다. 노드가 움직이는 동안에는
 * 그 영역이 따라오지 않아 로고가 가려지므로, 이동이 끝날 때까지 매 프레임 다시 맞춘다.
 */
export function followRoundLogos(
  graph: unknown,
  ids: string[],
  until: Promise<unknown>,
) {
  const element = (graph as RoundLogoGraph).context?.element;
  if (!element) return;
  let done = false;
  void until.finally(() => {
    done = true;
  });
  const frame = () => {
    for (const id of ids)
      for (const image of element.getElement(id)?.getShape('icon')?.children ??
        [])
        (image as { handleRadius?: () => void }).handleRadius?.();
    if (!done) requestAnimationFrame(frame);
  };
  frame();
}
