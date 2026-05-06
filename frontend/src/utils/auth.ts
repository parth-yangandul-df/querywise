const USER_INFO_KEY = 'qw_user';

export interface UserInfo {
  email: string;
  role: string;
  resource_id: number | null;
  employee_id?: string | null;
}

/** Store user info (role, email) after a successful login. The JWT itself lives in an HttpOnly cookie. */
export function setUserInfo(info: UserInfo): void {
  localStorage.setItem(USER_INFO_KEY, JSON.stringify(info));
}

/** Retrieve the stored user info, or null if not logged in. */
export function getUserInfo(): UserInfo | null {
  const raw = localStorage.getItem(USER_INFO_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as UserInfo;
  } catch {
    return null;
  }
}

/** Remove user info from storage. Actual cookie is cleared by calling POST /auth/logout. */
export function clearUserInfo(): void {
  localStorage.removeItem(USER_INFO_KEY);
}

/** Returns true if user info is present (i.e. the user has logged in this session). */
export function isAuthenticated(): boolean {
  return getUserInfo() !== null;
}

// ---------------------------------------------------------------------------
// Legacy shims — kept so any import that hasn't migrated yet compiles cleanly.
// These are intentional no-ops: the real JWT lives in an HttpOnly cookie,
// not in localStorage, so there is nothing to get or set here.
// ---------------------------------------------------------------------------

/** @deprecated Token is stored in an HttpOnly cookie set by the backend. */
export function getToken(): null {
  return null;
}

/** @deprecated Token is set by the backend as an HttpOnly cookie on login. */
export function setToken(_token: string): void {
  // no-op
}

/** @deprecated Use clearUserInfo() + POST /auth/logout instead. */
export function clearToken(): void {
  clearUserInfo();
}
