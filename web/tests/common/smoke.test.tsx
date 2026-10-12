import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { call } from '@/apis/auth/ApiService';
import EmptyState from '@/components/common/EmptyState';
import { createFakeServer, json } from '../support/fakeServer';

describe('테스트 환경', () => {
  test('컴포넌트를 jsdom에 그린다', () => {
    render(<EmptyState message="준비 중입니다." />);

    expect(screen.getByText('준비 중입니다.')).toBeTruthy();
  });

  test('가짜 서버가 공통 API 호출에 응답한다', async () => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/ping/:id', ({ params }) =>
      json({ id: params.id }),
    );

    await expect(call('/api/v1/ping/7', 'GET')).resolves.toEqual({ id: '7' });
    expect(server.calls('GET', '/api/v1/ping/:id')).toHaveLength(1);
  });
});
