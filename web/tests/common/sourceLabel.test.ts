import { describe, expect, it } from 'vitest';
import { sourceLabel } from '@/util/sourceLabel';

describe('sourceLabel', () => {
  it('names internal graph sources for people', () => {
    expect(sourceLabel('public_graph_snapshot')).toBe('ZOOP 관계 지도');
    expect(sourceLabel('postgresql+public_graph_snapshot')).toBe(
      'ZOOP 관계 지도',
    );
  });
  it('keeps unknown sources as they are', () => {
    expect(sourceLabel('합성 API')).toBe('합성 API');
  });
});
