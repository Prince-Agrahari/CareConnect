import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiClient, TOKEN_KEY } from "../api/client.js";
import { portalHome } from "../lib/format.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const clearSession = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
  }, []);

  const loadMe = useCallback(async () => {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (!stored) {
      setUser(null);
      setLoading(false);
      return null;
    }
    try {
      const { data } = await apiClient.get("/api/auth/me");
      setUser(data);
      setToken(stored);
      return data;
    } catch {
      clearSession();
      return null;
    } finally {
      setLoading(false);
    }
  }, [clearSession]);

  useEffect(() => {
    loadMe();
  }, [loadMe]);

  useEffect(() => {
    const onUnauthorized = () => {
      setToken(null);
      setUser(null);
    };
    window.addEventListener("careconnect:unauthorized", onUnauthorized);
    return () => window.removeEventListener("careconnect:unauthorized", onUnauthorized);
  }, []);

  const login = async (email, password) => {
    const { data } = await apiClient.post("/api/auth/login", { email, password });
    localStorage.setItem(TOKEN_KEY, data.access_token);
    setToken(data.access_token);
    setUser(data.user);
    return data.user;
  };

  const register = async (payload) => {
    await apiClient.post("/api/auth/register", payload);
    return login(payload.email, payload.password);
  };

  const logout = () => {
    clearSession();
  };

  const value = useMemo(
    () => ({
      token,
      user,
      loading,
      isAuthenticated: Boolean(user),
      login,
      register,
      logout,
      reload: loadMe,
      home: portalHome(user?.role),
    }),
    [token, user, loading, loadMe]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
