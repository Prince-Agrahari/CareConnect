import axios from "axios";

export const TOKEN_KEY = "careconnect_token";

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000",
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status;
    const url = String(error?.config?.url || "");
    const skip = url.includes("/api/auth/login") || url.includes("/api/auth/register");
    if (status === 401 && !skip) {
      localStorage.removeItem(TOKEN_KEY);
      window.dispatchEvent(new Event("careconnect:unauthorized"));
    }
    return Promise.reject(error);
  }
);
