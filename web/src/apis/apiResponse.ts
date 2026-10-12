import type { ApiResponse } from './commonType';

export function getResponseData<T>(response: ApiResponse<T>): T {
  return response.data;
}
