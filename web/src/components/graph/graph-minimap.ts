// Shared by the G6 option and its camera-fit adapter (padding on each side).
export const MINIMAP_PADDING = 10;

type MinimapHost = {
  getPluginInstance: (key: string) => unknown;
  off: (event: string, handler: () => void) => unknown;
};
type Bounds = { min: number[]; max: number[]; center: number[] };
type Camera = {
  createLandmark: (
    name: string,
    fit: { position: number[]; focalPoint: number[]; zoom: number },
  ) => unknown;
  gotoLandmark: (landmark: unknown, duration: number) => unknown;
};
type Overview = {
  onDraw: () => void;
  onRender: () => void;
  renderMinimap: () => void;
  setCamera: () => void;
  canvas?: {
    getConfig: () => { width: number; height: number };
    getRoot: () => { childNodes: unknown[]; getBounds: () => Bounds };
    getCamera: () => Camera;
  };
};

const prepared = new WeakSet<Overview>();

/** G6 5.1 minimap uses the main element layer's bounds, including our dimming cover.
 * Fit its own filtered key-shape clones instead. Keep the G6 mask and drag handlers.
 * This adapter also runs after cloning: G6's initial camera fit happens before it.
 */
function fitContent(plugin: Overview) {
  const render = plugin.renderMinimap.bind(plugin);
  let previous = '';
  let previousCamera: Camera | undefined;
  plugin.setCamera = () => {
    const canvas = plugin.canvas;
    if (!canvas || !canvas.getRoot().childNodes.length) return;
    const { min, max, center } = canvas.getRoot().getBounds();
    const { width, height } = canvas.getConfig();
    const values = [
      min[0],
      min[1],
      max[0],
      max[1],
      center[0],
      center[1],
      width,
      height,
    ];
    if (
      !values.every(Number.isFinite) ||
      width <= MINIMAP_PADDING * 2 ||
      height <= MINIMAP_PADDING * 2 ||
      max[0] < min[0] ||
      max[1] < min[1]
    )
      return;
    const camera = canvas.getCamera();
    const key = values.join(',');
    // Pan/zoom changes only G6's viewport mask, not the overview's full-graph camera.
    if (key === previous && camera === previousCamera) return;
    const point = [center[0], center[1], center[2] ?? 0];
    const zoom = Math.min(
      (width - MINIMAP_PADDING * 2) / Math.max(1, max[0] - min[0]),
      (height - MINIMAP_PADDING * 2) / Math.max(1, max[1] - min[1]),
    );
    camera.gotoLandmark(
      camera.createLandmark(`graph-overview-content:${key}`, {
        position: point,
        focalPoint: point,
        zoom,
      }),
      0,
    );
    previous = key;
    previousCamera = camera;
  };
  plugin.renderMinimap = () => {
    render();
    plugin.setCamera();
  };
}

// D-GRP-01: retain data-only minimap redraws instead of copying shapes on every hover.
export function configureMinimap(graph: MinimapHost) {
  const plugin = graph.getPluginInstance('graph-overview') as unknown as
    Overview | undefined;
  if (!plugin?.onDraw || !plugin.onRender) return null;
  if (!prepared.has(plugin) && typeof plugin.renderMinimap === 'function') {
    fitContent(plugin);
    prepared.add(plugin);
  }
  graph.off('afterdraw', plugin.onDraw);
  graph.off('afteranimate', plugin.onRender);
  return plugin.onRender;
}
