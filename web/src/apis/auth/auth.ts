export const ACCESS_TOKEN_KEY = 'accessToken';

export function getAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function setAccessToken(token: string) {
  localStorage.setItem(ACCESS_TOKEN_KEY, token);
}

export function clearAuthentication() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  sessionStorage.removeItem('oauth_state');
}

export function isAuthenticated() {
  return Boolean(getAccessToken());
}
