// FS003/FS006: direct /api/v1 contract DTOs; the session cookie is HttpOnly.
export type { Session as MemberSession } from './index';
export interface SignupTerm {
  id: string;
  title: string;
  required: boolean;
  body: string | null;
  version: string | null;
  bodyAvailable: boolean;
}
export interface SignupBody {
  email: string;
  password: string;
  displayName?: string;
  agreements: { id: string; version: string; accepted: boolean }[];
}
