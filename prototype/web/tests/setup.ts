// jsdom에는 없지만 앱 화면(Radix 부품·반응형 훅·스크롤)이 호출하는 브라우저 기능을 채운다.
// 동작을 흉내 내는 것이 목적이 아니라 "없어서 터지지 않게" 하는 최소 대역이다.
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// 지도 캔버스(Cytoscape)는 jsdom에서 그릴 수 없다. 노드를 버튼 목록으로 내보내는 대역으로 바꾼다.
// 지도 화면(메인)을 올리지 않는 시험에서도 Cytoscape 플러그인 등록이 시험마다 되풀이되지 않는다.
vi.mock("@/components/domain/graph-canvas", () => import("./support/graph-canvas-double"));

/** `(max-width: 768px)`만 현재 창 너비로 판정한다. 나머지(동작 줄이기·색 구성)는 모두 꺼진 상태다. */
function matchMediaStub(query: string): MediaQueryList {
  const max = /\(max-width:\s*(\d+)px\)/.exec(query);
  return {
    media: query,
    matches: max ? window.innerWidth <= Number(max[1]) : false,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  };
}
window.matchMedia = matchMediaStub;

class ObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}
globalThis.ResizeObserver = ObserverStub as unknown as typeof ResizeObserver;
globalThis.IntersectionObserver = ObserverStub as unknown as typeof IntersectionObserver;

Element.prototype.scrollIntoView = () => {};
window.scrollTo = () => {};
// Radix Select·Tooltip·Dialog가 포인터 캡처를 확인한다.
Element.prototype.hasPointerCapture = () => false;
Element.prototype.setPointerCapture = () => {};
Element.prototype.releasePointerCapture = () => {};

// 앱은 일시 장애(5xx·연결 실패)를 1초 뒤 한 번 더 시도하므로, 오류 안내가 뜰 때까지 기본 1초보다 넉넉히 기다린다.
configure({ asyncUtilTimeout: 4000 });

afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
});
