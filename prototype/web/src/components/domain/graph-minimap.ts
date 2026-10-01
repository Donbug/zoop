// GraphCanvas 미니맵(G7): cytoscape-navigator(MIT)로 전체 조망 + 지금 보는 영역 사각형. 사각형을 끌거나 조망을 누르면 화면이 따라간다.
// 포인터 전용 보조 수단이라 캔버스가 aria-hidden 패널을 주고, 키보드 대체 수단은 도구 막대(확대·축소·화면에 맞추기)다.
// 성능: 확장의 기본 동작은 매 렌더(확대·이동 프레임 포함)마다 cy.png로 썸네일을 다시 그린다. 그 처리기를 떼고,
// 요소·위치·스타일·크기가 바뀐 뒤 화면 이동이 멈춘 상태로 REFRESH_DELAY가 지났을 때만 한 번 그린다.
// 보이는 영역 사각형은 확장이 zoom·pan 이벤트마다 CSS 위치만 바꾸므로 그대로 둔다.
import cytoscape, { type Core } from "cytoscape";
import navigator, { type Navigator, type NavigatorOptions } from "cytoscape-navigator";

cytoscape.use(navigator);

/** 이 개수를 넘는 노드가 보일 때만 미니맵을 둔다(데스크톱). */
export const MINIMAP_MIN_NODES = 60;

/** 마지막 변경·화면 이동 뒤 썸네일을 다시 그리기까지 기다리는 시간(ms) */
const REFRESH_DELAY = 300;

/** panelId 요소(비어 있는 div)에 미니맵을 붙인다. 반환값은 정리 함수(확장의 cy 처리기까지 뗀다). */
export function attachMinimap(cy: Core, panelId: string) {
  const nav = (cy as Core & { navigator(options: NavigatorOptions): Navigator }).navigator({
    container: `#${panelId}`,
    viewLiveFramerate: 0,
    removeCustomContainer: false,
    rerenderDelay: 50,
  });
  // 타입 정의에 없는 Core.offRender(onRender의 짝)로 확장의 매 렌더 처리기를 뗀다.
  (cy as Core & { offRender(handler: () => void): void }).offRender(nav._onRenderHandler);

  let timer = 0;
  let changedAt = 0;
  let movedAt = 0;
  const refresh = () => {
    const idle = performance.now() - Math.max(changedAt, movedAt);
    if (idle < REFRESH_DELAY) {
      timer = window.setTimeout(refresh, REFRESH_DELAY - idle);
      return;
    }
    timer = 0;
    if (!cy.destroyed()) nav._onRenderHandler();
  };
  // 요소마다 오는 이벤트라 시각만 적고, 예약은 한 번만 한다.
  const onChange = () => {
    changedAt = performance.now();
    if (!timer) timer = window.setTimeout(refresh, REFRESH_DELAY);
  };
  const onViewport = () => void (movedAt = performance.now());
  cy.on("add remove position style resize", onChange);
  cy.on("viewport", onViewport);
  nav._onRenderHandler();

  return () => {
    window.clearTimeout(timer);
    if (!cy.destroyed()) {
      cy.off("add remove position style resize", onChange);
      cy.off("viewport", onViewport);
      nav._removeCyListeners();
    }
    nav.destroy();
  };
}
