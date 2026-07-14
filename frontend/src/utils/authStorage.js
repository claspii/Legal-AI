/**
 * Cookie operations and auth storage utility.
 */

const getCookie = (name) => {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
};

const setCookie = (name, value, days) => {
  let expires = "";
  if (days) {
    const date = new Date();
    date.setTime(date.getTime() + days * 24 * 60 * 60 * 1000);
    expires = `; expires=${date.toUTCString()}`;
  }
  document.cookie = `${name}=${value || ""}${expires}; path=/; SameSite=Lax`;
};

const removeCookie = (name) => {
  document.cookie = `${name}=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT; SameSite=Lax`;
};

const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_KEY = 'user';

export const authStorage = {
  setTokens(accessToken, refreshToken, rememberMe = false) {
    const days = rememberMe ? 7 : null; // 7 days or session cookie
    
    setCookie(ACCESS_TOKEN_KEY, accessToken, days);
    setCookie(REFRESH_TOKEN_KEY, refreshToken, days);
    
    // Sync to localStorage for fallback compat
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
    localStorage.setItem('remember_me', rememberMe ? 'true' : 'false');
  },

  getAccessToken() {
    let token = getCookie(ACCESS_TOKEN_KEY);
    if (!token) {
      token = localStorage.getItem(ACCESS_TOKEN_KEY);
    }
    return token;
  },

  getRefreshToken() {
    let token = getCookie(REFRESH_TOKEN_KEY);
    if (!token) {
      token = localStorage.getItem(REFRESH_TOKEN_KEY);
    }
    return token;
  },

  saveUser(user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  },

  getUser() {
    const userStr = localStorage.getItem(USER_KEY);
    try {
      return userStr ? JSON.parse(userStr) : null;
    } catch {
      return null;
    }
  },

  clear() {
    removeCookie(ACCESS_TOKEN_KEY);
    removeCookie(REFRESH_TOKEN_KEY);
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem('remember_me');
  }
};
