import { create } from "zustand";

import { setupApi } from "../api/endpoints";
import type { SetupStatus } from "../api/types";

type SetupState = "unknown" | "loading" | "required" | "ready";

interface SetupStore {
  state: SetupState;
  status: SetupStatus | null;
  error: string | null;
  ensure: () => Promise<void>;
  refresh: () => Promise<void>;
}

let inflight: Promise<void> | null = null;

export const useSetup = create<SetupStore>()((set, get) => ({
  state: "unknown",
  status: null,
  error: null,
  ensure: async () => {
    if (get().state === "ready" || get().state === "required") return;
    if (inflight) return inflight;
    set({ state: "loading", error: null });
    inflight = setupApi
      .status()
      .then((status) => {
        set({
          state: status.initialized ? "ready" : "required",
          status,
        });
      })
      .catch((error: unknown) => {
        set({
          state: "unknown",
          error: error instanceof Error ? error.message : "无法连接后端服务",
        });
        throw error;
      })
      .finally(() => {
        inflight = null;
      });
    return inflight;
  },
  refresh: async () => {
    const status = await setupApi.status();
    set({ state: status.initialized ? "ready" : "required", status, error: null });
  },
}));
