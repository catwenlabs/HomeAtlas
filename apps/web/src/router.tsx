import {
  Link,
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  redirect,
} from "@tanstack/react-router";

import { AppShell } from "./components/AppShell";
import { Button, Card } from "./components/ui";
import { AccountsPage } from "./pages/AccountsPage";
import { CategoriesPage } from "./pages/CategoriesPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ImportsPage } from "./pages/ImportsPage";
import { LoginPage } from "./pages/LoginPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SetupPage } from "./pages/SetupPage";
import { StatisticsPage } from "./pages/StatisticsPage";
import { TransactionsPage } from "./pages/TransactionsPage";
import { TransfersPage } from "./pages/TransfersPage";
import { useAuth } from "./store/auth";
import { useSetup } from "./store/setup";

const rootRoute = createRootRoute({
  component: () => <Outlet />,
  errorComponent: RouteError,
  notFoundComponent: NotFound,
});

const setupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/setup",
  beforeLoad: async () => {
    await useSetup.getState().ensure();
    if (useSetup.getState().state === "ready") {
      throw redirect({ to: "/" });
    }
  },
  component: SetupPage,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  beforeLoad: async () => {
    await useSetup.getState().ensure();
    if (useSetup.getState().state === "required") {
      throw redirect({ to: "/setup" });
    }
    if (useAuth.getState().token) {
      throw redirect({ to: "/" });
    }
  },
  component: LoginPage,
});

const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  component: AppShell,
  beforeLoad: async () => {
    await useSetup.getState().ensure();
    if (useSetup.getState().state === "required") {
      throw redirect({ to: "/setup" });
    }
    if (!useAuth.getState().token) {
      throw redirect({ to: "/login" });
    }
  },
});

const dashboardRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/",
  component: DashboardPage,
});

const transactionsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/transactions",
  component: TransactionsPage,
});

const accountsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/accounts",
  component: AccountsPage,
});

const categoriesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/categories",
  component: CategoriesPage,
});

const transfersRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/transfers",
  component: TransfersPage,
});

const statisticsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/statistics",
  component: StatisticsPage,
});

const importsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/imports",
  component: ImportsPage,
});

const settingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/settings",
  component: SettingsPage,
});

const routeTree = rootRoute.addChildren([
  setupRoute,
  loginRoute,
  appRoute.addChildren([
    dashboardRoute,
    transactionsRoute,
    accountsRoute,
    categoriesRoute,
    transfersRoute,
    statisticsRoute,
    importsRoute,
    settingsRoute,
  ]),
]);

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  defaultPreloadStaleTime: 0,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

function RouteError({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="max-w-md p-6 text-center">
        <h1 className="text-lg font-semibold text-ink">页面加载失败</h1>
        <p className="mt-2 text-sm text-ink/55">{message}</p>
        <Button className="mt-4" onClick={() => window.location.reload()}>
          重新加载
        </Button>
      </Card>
    </div>
  );
}

function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="max-w-md p-6 text-center">
        <h1 className="text-lg font-semibold text-ink">页面不存在</h1>
        <p className="mt-2 text-sm text-ink/55">你访问的地址没有对应的页面。</p>
        <Link
          to="/"
          className="mt-4 inline-flex rounded-xl bg-primary-600 px-4 py-2.5 text-sm font-medium text-white"
        >
          返回总览
        </Link>
      </Card>
    </div>
  );
}
