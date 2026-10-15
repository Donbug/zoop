import { call } from '@/apis/auth/ApiService';
import { acceptMemberSession } from '@/apis/auth/member-session';
import type { Session } from '@/types/auth';

export async function setTutorialCompleted(completed: boolean) {
  const session = await call<Session>('/api/v1/auth/tutorial', 'PUT', {
    completed,
  });
  acceptMemberSession(session);
  return session;
}
