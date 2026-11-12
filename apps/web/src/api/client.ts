import axios, { AxiosError, type AxiosResponse } from "axios";

import { useAuth } from "../store/auth";
import type { Envelope } from "./types";

export class ApiError extends Error {
  code: string;
  status?: number;

  constructor(message: string, code = "API_ERROR", status?: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export const api = axios.create({
  baseURL: "/api/v1",
  timeout: 30000,
});

api.interceptors.request.use((config) => {
  const token = useAuth.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<Envelope<unknown>>) => {
    const code = error.response?.data?.error_code;
    if (error.response?.status === 401 && code !== "AUTH_INVALID_CREDENTIALS") {
      useAuth.getState().clear();
      if (!window.location.pathname.startsWith("/login")) {
        window.location.assign("/login");
      }
    }
    return Promise.reject(error);
  },
);

export async function unwrap<T>(promise: Promise<AxiosResponse<Envelope<T>>>): Promise<T> {
  try {
    const response = await promise;
    return response.data.data;
  } catch (error) {
    if (error instanceof AxiosError) {
      const payload = error.response?.data;
      throw new ApiError(
        payload?.message ?? error.message,
        payload?.error_code ?? "API_ERROR",
        error.response?.status,
      );
    }
    throw error;
  }
}
