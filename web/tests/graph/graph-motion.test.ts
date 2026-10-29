import { afterEach, describe, expect, it, vi } from 'vitest';
import { cameraMotion } from '@/components/graph/graph-motion';

afterEach(() => vi.unstubAllGlobals());

describe('D-GRP-01 cameraMotion', () => {
  it('matchMedia가 없으면(테스트·오래된 브라우저) 바로 옮긴다', () => {
    vi.stubGlobal('matchMedia', undefined);
    expect(cameraMotion('select')).toBe(false);
  });

  it('동작 줄이기를 켜면 바로 옮기고, 아니면 이동 종류별 길이로 움직인다', () => {
    let reduce = true;
    vi.stubGlobal('matchMedia', () => ({ matches: reduce }));
    expect(cameraMotion('zoom')).toBe(false);
    reduce = false;
    const easing = 'cubic-bezier(0.35, 0, 0.35, 1)';
    expect(cameraMotion('select')).toEqual({ duration: 300, easing });
    expect(cameraMotion('zoom')).toEqual({ duration: 250, easing });
    expect(cameraMotion('fit')).toEqual({ duration: 300, easing });
    expect(cameraMotion('layout')).toEqual({ duration: 600, easing });
  });
});
