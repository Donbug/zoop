import { describe, expect, it, vi } from 'vitest';
import { configureMinimap } from '@/components/graph/graph-minimap';

function fixture() {
  let ready = false;
  let zoom = 1;
  const createLandmark = vi.fn((_name: string, fit: { zoom: number }) => fit);
  const camera = {
    createLandmark,
    gotoLandmark: vi.fn((fit: { zoom: number }) => {
      zoom = fit.zoom;
    }),
  };
  const root = {
    childNodes: [] as object[],
    getBounds: () => ({
      min: [-200, -100, 0],
      max: [200, 100, 0],
      center: [0, 0, 0],
    }),
  };
  const canvas = {
    getRoot: () => root,
    getCamera: () => camera,
    getConfig: () => ({ width: 192, height: 128 }),
  };
  const maskZoom = vi.fn();
  const plugin = {
    get canvas() {
      return ready ? canvas : undefined;
    },
    onDraw: vi.fn(),
    setCamera: () => {
      zoom = 108 / 2_000_000;
    },
    renderMinimap: () => {
      ready = true;
      plugin.setCamera(); // G6 initializes/fits before it appends the cloned shapes.
      root.childNodes = [{}];
    },
    onRender: () => {
      plugin.renderMinimap();
      maskZoom(zoom);
    },
  };
  return {
    plugin,
    root,
    camera,
    maskZoom,
    graph: { getPluginInstance: vi.fn(() => plugin), off: vi.fn() },
  };
}

describe('D-GRP-01 minimap content bounds', () => {
  it('fits actual miniature shapes before drawing the viewport, ignoring the million-unit dimming cover', () => {
    const f = fixture();
    configureMinimap(f.graph)?.();
    expect(f.maskZoom).toHaveBeenLastCalledWith(0.43); // 172px / 400 graph units
    expect(f.camera.createLandmark).toHaveBeenCalledWith(expect.any(String), {
      position: [0, 0, 0],
      focalPoint: [0, 0, 0],
      zoom: 0.43,
    });
  });

  it('keeps the same overview camera on pan and does not wrap the same plugin again', () => {
    const f = fixture();
    configureMinimap(f.graph)?.();
    const draw = f.plugin.renderMinimap;
    configureMinimap(f.graph);
    expect(f.plugin.renderMinimap).toBe(draw);
    f.plugin.setCamera();
    f.plugin.setCamera();
    expect(f.camera.createLandmark).toHaveBeenCalledTimes(1);
    expect(f.graph.off).toHaveBeenCalledWith('afterdraw', f.plugin.onDraw);
    expect(f.graph.off).toHaveBeenCalledWith('afteranimate', f.plugin.onRender);
  });

  it('does not create a camera with invalid bounds when the filtered thumbnail is empty', () => {
    const f = fixture();
    configureMinimap(f.graph);
    expect(() => f.plugin.setCamera()).not.toThrow();
    expect(f.camera.createLandmark).not.toHaveBeenCalled();
  });

  it('refits changed filtered contents and ignores nonfinite bounds', () => {
    const f = fixture();
    const render = configureMinimap(f.graph)!;
    render();
    f.root.getBounds = () => ({
      min: [-400, -200, 0],
      max: [400, 200, 0],
      center: [0, 0, 0],
    });
    render();
    expect(f.maskZoom).toHaveBeenLastCalledWith(0.215);
    expect(f.camera.createLandmark).toHaveBeenCalledTimes(2);
    f.root.getBounds = () => ({
      min: [-Infinity, 0, 0],
      max: [Infinity, 0, 0],
      center: [NaN, 0, 0],
    });
    render();
    expect(f.camera.createLandmark).toHaveBeenCalledTimes(2);
  });
});
