import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { Session, User, Household } from "../api/types";

interface AuthState {
  token: string | null;
  user: User | null;
  household: Household | null;
  setSession: (session: Session) => void;
  setHousehold: (household: Household) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      household: null,
      setSession: (session) =>
        set({
          token: session.access_token,
          user: session.user,
          household: session.household,
        }),
      setHousehold: (household) => set({ household }),
      clear: () => set({ token: null, user: null, household: null }),
    }),
    { name: "homeatlas-auth" },
  ),
);
