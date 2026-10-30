import type { Graph } from '@antv/g6';

// D-GRP-01: dimming every other element through G6 states re-renders each one
// (labels included), which takes seconds with hundreds of nodes. Instead one
// translucent cover in the map colour sits above the elements, and only the
// elements that stay bright are raised above it. Paper at 65% over an element
// looks the same as that element at opacity 0.35.
const COVER_Z = 1000;
const EDGE_Z = 1001;
const NODE_Z = 1002;
const COVER_OPACITY = 0.65;

type Shape = {
  id?: string;
  nodeName?: string;
  parentNode?: Shape | null;
  childNodes?: Shape[];
  style: Record<string, unknown>;
  appendChild?: (child: Shape) => void;
};
type SceneDocument = {
  documentElement?: Shape;
  createElement?: (tag: string, options: object) => Shape;
};
type State = {
  cover: Shape;
  elements: Map<string, Shape>;
  /** Raised element id → its own zIndex before raising. */
  raised: Map<string, unknown>;
  dimmed: boolean;
  bright: Map<string, 'node' | 'edge'>;
  color: string;
};
const states = new WeakMap<Graph, State>();

/** G6 keeps every node and edge as a direct child of one group under the scene root. */
function elementLayer(graph: Graph) {
  if (graph.destroyed || typeof graph.getCanvas !== 'function') return null;
  const document = graph.getCanvas()?.document as unknown as
    SceneDocument | undefined;
  const layer = document?.documentElement?.childNodes?.find((child) =>
    child.childNodes?.some((item) => item.id),
  );
  return layer && document?.createElement ? { document, layer } : null;
}

function element(state: State, layer: Shape, id: string) {
  const found = state.elements.get(id);
  if (found?.parentNode === layer) return found;
  // setData can replace elements; rebuild the index from the layer.
  state.elements.clear();
  for (const child of layer.childNodes ?? [])
    if (child.id) state.elements.set(child.id, child);
  return state.elements.get(id);
}

function raise(state: State, layer: Shape) {
  if (!state.dimmed) return;
  for (const [id, kind] of state.bright) {
    const shape = element(state, layer, id);
    if (!shape) continue;
    const z = kind === 'node' ? NODE_Z : EDGE_Z;
    if (shape.style.zIndex === z) continue;
    // G6 restores its own zIndex whenever it redraws an element; keep that value.
    state.raised.set(id, shape.style.zIndex);
    shape.style.zIndex = z;
  }
}

/** Show or hide the cover and raise the elements that stay bright. */
export function applyMapDimming(
  graph: Graph,
  dimmed: boolean,
  bright: Map<string, 'node' | 'edge'>,
  color: string,
) {
  const scene = elementLayer(graph);
  if (!scene) return;
  let state = states.get(graph);
  if (!state) {
    const cover = scene.document.createElement!('rect', {
      style: {
        x: -1e6,
        y: -1e6,
        width: 2e6,
        height: 2e6,
        fill: color,
        fillOpacity: COVER_OPACITY,
        zIndex: COVER_Z,
        pointerEvents: 'none',
        visibility: 'hidden',
      },
    });
    state = {
      cover,
      elements: new Map(),
      raised: new Map(),
      dimmed: false,
      bright: new Map(),
      color,
    };
    states.set(graph, state);
  }
  // The cover must be a sibling of the elements for zIndex to order them.
  if (state.cover.parentNode !== scene.layer)
    scene.layer.appendChild?.(state.cover);
  for (const [id, z] of state.raised) {
    if (dimmed && bright.has(id)) continue;
    const shape = element(state, scene.layer, id);
    if (shape && Number(shape.style.zIndex) >= COVER_Z) shape.style.zIndex = z;
    state.raised.delete(id);
  }
  state.dimmed = dimmed;
  state.bright = bright;
  if (state.color !== color) {
    state.color = color;
    state.cover.style.fill = color;
  }
  state.cover.style.visibility = dimmed ? 'visible' : 'hidden';
  raise(state, scene.layer);
}

/** After any G6 draw: elements it redrew are back at their own zIndex. */
export function restoreMapDimming(graph: Graph) {
  const state = states.get(graph);
  const scene = elementLayer(graph);
  if (!state || !scene) return;
  if (state.cover.parentNode !== scene.layer)
    scene.layer.appendChild?.(state.cover);
  raise(state, scene.layer);
}
