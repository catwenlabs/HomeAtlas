import { Link, Outlet, useNavigate } from "@tanstack/react-router";
import {
  ArrowLeftRight,
  BarChart3,
  LayoutDashboard,
  LogOut,
  Scale,
  Settings,
  Tags,
  Upload,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";

import { authApi } from "../api/endpoints";
import { useAuth } from "../store/auth";
import { Button } from "./ui";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "总览", icon: LayoutDashboard },
  { to: "/transactions", label: "收支记录", icon: ArrowLeftRight },
  { to: "/accounts", label: "账户", icon: Wallet },
  { to: "/transfers", label: "转账", icon: ArrowLeftRight },
  { to: "/categories", label: "分类", icon: Tags },
  { to: "/assets", label: "资产负债", icon: Scale },
  { to: "/statistics", label: "统计", icon: BarChart3 },
  { to: "/imports", label: "导入", icon: Upload },
  { to: "/settings", label: "设置", icon: Settings },
];

export function AppShell() {
  const navigate = useNavigate();
  const user = useAuth((state) => state.user);
  const household = useAuth((state) => state.household);
  const clear = useAuth((state) => state.clear);
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await authApi.logout();
    } catch {
      // The token is stateless; a failed logout must not trap the user.
    } finally {
      clear();
      setLoggingOut(false);
      await navigate({ to: "/login" });
    }
  }

  return (
    <div className="min-h-full lg:flex">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-ink/8 bg-white/70 px-4 py-6 backdrop-blur lg:flex">
        <Link to="/" className="mb-8 flex items-center gap-3 px-2">
          <span className="grid h-10 w-10 place-items-center rounded-2xl bg-primary-600 text-base font-semibold text-white">
            HA
          </span>
          <span>
            <span className="block text-sm font-semibold tracking-tight text-ink">HomeAtlas</span>
            <span className="block text-xs text-ink/45">家庭财务全景</span>
          </span>
        </Link>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              activeOptions={{ exact: item.to === "/" }}
              className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-ink/60 transition hover:bg-ink/5 hover:text-ink"
              activeProps={{ className: "bg-primary-50 text-primary-800 font-medium" }}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="mt-6 rounded-2xl border border-ink/8 bg-canvas/60 p-3">
          <p className="truncate text-sm font-medium text-ink">{household?.name ?? "家庭"}</p>
          <p className="mt-0.5 text-xs text-ink/45">
            {user?.display_name ?? user?.username} · {user?.role === "owner" ? "管理员" : "成员"}
          </p>
          <Button
            variant="ghost"
            className="mt-2 h-9 w-full justify-start px-2 text-xs"
            onClick={handleLogout}
            disabled={loggingOut}
          >
            <LogOut className="h-3.5 w-3.5" />
            {loggingOut ? "退出中…" : "退出登录"}
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 border-b border-ink/8 bg-canvas/85 backdrop-blur lg:hidden">
          <div className="flex items-center justify-between px-4 py-3">
            <Link to="/" className="flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-xl bg-primary-600 text-xs font-semibold text-white">
                HA
              </span>
              <span className="text-sm font-semibold text-ink">HomeAtlas</span>
            </Link>
            <div className="flex items-center gap-2">
              <span className="max-w-32 truncate text-xs text-ink/50">{household?.name}</span>
              <Button variant="ghost" className="h-9 px-2" onClick={handleLogout}>
                <LogOut className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <nav className="no-scrollbar flex gap-1 overflow-x-auto px-3 pb-2">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                activeOptions={{ exact: item.to === "/" }}
                className="flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs text-ink/60"
                activeProps={{ className: "bg-primary-100 text-primary-800 font-medium" }}
              >
                <item.icon className="h-3.5 w-3.5" />
                {item.label}
              </Link>
            ))}
          </nav>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 lg:px-10 lg:py-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
