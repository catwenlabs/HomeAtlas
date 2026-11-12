import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { LogIn } from "lucide-react";
import { useState } from "react";

import { authApi } from "../api/endpoints";
import { Button, Card, ErrorBanner, Field, Input } from "../components/ui";
import { errorMessage } from "../lib/utils";
import { useAuth } from "../store/auth";

export function LoginPage() {
  const navigate = useNavigate();
  const setSession = useAuth((state) => state.setSession);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const login = useMutation({
    mutationFn: () => authApi.login(username.trim(), password),
    onSuccess: async (session) => {
      setSession(session);
      await navigate({ to: "/" });
    },
  });

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-7 text-center">
          <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-primary-600 text-sm font-semibold text-white">
            HA
          </span>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight text-ink">HomeAtlas</h1>
          <p className="mt-1 text-sm text-ink/50">登录你的家庭账本</p>
        </div>
        <Card className="p-6">
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              login.mutate();
            }}
          >
            <Field label="用户名">
              <Input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                autoFocus
              />
            </Field>
            <Field label="密码">
              <Input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
              />
            </Field>
            {login.isError ? <ErrorBanner message={errorMessage(login.error)} /> : null}
            <Button type="submit" className="w-full" disabled={login.isPending}>
              {login.isPending ? "登录中…" : "登录"}
              <LogIn className="h-4 w-4" />
            </Button>
          </form>
        </Card>
        <p className="mt-4 text-center text-xs text-ink/40">
          忘记密码？请联系家庭管理员重置。
        </p>
      </div>
    </div>
  );
}
