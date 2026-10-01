// cytoscape-navigator 2.0.2는 타입 정의를 제공하지 않는다. 확장 등록과 미니맵(graph-minimap)이 쓰는 모양만 선언한다.
declare module "cytoscape-navigator" {
  import type { Ext } from "cytoscape";

  export interface NavigatorOptions {
    /** "#id" 또는 ".class" 문자열만 받는다(요소를 직접 넘기면 body에 새 패널을 만든다). */
    container: string;
    /** 끌기 중 그래프 이동 빈도. 0이면 즉시, false면 놓을 때만. */
    viewLiveFramerate?: number | false;
    dblClickDelay?: number;
    /** false면 destroy 때 패널을 지우지 않고 비운다. */
    removeCustomContainer?: boolean;
    /** 썸네일 다시 그리기 제한(ms) */
    rerenderDelay?: number;
  }

  export interface Navigator {
    destroy(): void;
    /** 썸네일을 다시 그리는 onRender 처리기(rerenderDelay로 제한됨). 내부 필드. */
    _onRenderHandler: () => void;
    /** cy에 붙인 zoom·pan·resize·onRender 처리기를 뗀다(destroy는 이것을 부르지 않는다). 내부 메서드. */
    _removeCyListeners(): void;
  }

  const navigator: Ext;
  export default navigator;
}
