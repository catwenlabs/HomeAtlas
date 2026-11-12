import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, UserPlus } from "lucide-react";
import { useState } from "react";

import { householdsApi, setupApi, usersApi } from "../api/endpoints";
import type { Household, User } from "../api/types";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ErrorBanner,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  Spinner,
  SuccessBanner,
} from "../components/ui";
import { useCurrencies } from "../hooks/useReference";
import { errorMessage } from "../lib/utils";
import { useAuth } from "../store/auth";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const authUser = useAuth((state) => state.user);
  const household = useAuth((state) => state.household);
  const setHousehold = useAuth((state) => state.setHousehold);
  const currencies = useCurrencies();
  const setupOptions = useQuery({
    queryKey: ["setup-options"],
    queryFn: setupApi.options,
    staleTime: 60 * 60 * 1000,
  });
  const [message, setMessage] = useState<string | null>(null);
  const [householdForm, setHouseholdForm] = useState({
    name: household?.name ?? "",
    base_currency: household?.base_currency ?? "CNY",
    timezone: household?.timezone ?? "Asia/Shanghai",
  });
  const [memberModal, setMemberModal] = useState(false);
  const [memberForm, setMemberForm] = useState({
    username: "",
    display_name: "",
    password: "",
    role: "member" as "member" | "owner",
  });
  const [passwordTarget, setPasswordTarget] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const users = useQuery({
    queryKey: ["users"],
    queryFn: usersApi.list,
    enabled: Boolean(authUser),
  });

  const updateHousehold = useMutation({
    mutationFn: () =>
      household
        ? householdsApi.update(household.id, {
            name: householdForm.name.trim(),
            base_currency: householdForm.base_currency,
            timezone: householdForm.timezone,
          })
        : Promise.reject(new Error("家庭信息未加载")),
    onSuccess: (updated: Household) => {
      setHousehold(updated);
      setMessage("家庭信息已更新");
      queryClient.invalidateQueries({ queryKey: ["statistics"] });
      queryClient.invalidateQueries({ queryKey: ["setup-options"] });
    },
  });

  const createMember = useMutation({
    mutationFn: () =>
      usersApi.create({
        username: memberForm.username.trim(),
        display_name: memberForm.display_name.trim(),
        password: memberForm.password,
        role: memberForm.role,
      }),
    onSuccess: async () => {
      setMemberModal(false);
      setMemberForm({ username: "", display_name: "", password: "", role: "member" });
      setMessage("家庭成员已添加");
      await queryClient.invalidateQueries({ queryKey: ["users"] });
    },
  });

  const updateMember = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Parameters<typeof usersApi.update>[1] }) =>
      usersApi.update(id, payload),
    onSuccess: async () => {
      setPasswordTarget(null);
      setNewPassword("");
      setMessage("成员信息已更新");
      await queryClient.invalidateQueries({ queryKey: ["users"] });
    },
  });

  const isOwner = authUser?.role === "owner";
  const mutationError = updateHousehold.error ?? createMember.error ?? updateMember.error;

  return (
    <div>
      <PageHeader
        eyebrow="Settings"
        title="设置"
        description="家庭信息、本位币与成员管理。"
      />

      {message ? (
        <div className="mb-4">
          <SuccessBanner message={message} />
        </div>
      ) : null}
      {mutationError ? (
        <div className="mb-4">
          <ErrorBanner message={errorMessage(mutationError)} />
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="家庭信息" description="本位币决定统计与报表的汇总币种" />
          <div className="space-y-4 p-5">
            <Field label="家庭名称">
              <Input
                value={householdForm.name}
                onChange={(event) =>
                  setHouseholdForm((value) => ({ ...value, name: event.target.value }))
                }
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="本位币">
                <Select
                  value={householdForm.base_currency}
                  onChange={(event) =>
                    setHouseholdForm((value) => ({ ...value, base_currency: event.target.value }))
                  }
                >
                  {currencies.data?.map((currency) => (
                    <option key={currency.code} value={currency.code}>
                      {currency.code} · {currency.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="时区">
                <Select
                  value={householdForm.timezone}
                  onChange={(event) =>
                    setHouseholdForm((value) => ({ ...value, timezone: event.target.value }))
                  }
                >
                  {setupOptions.data?.timezones.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <div className="flex justify-end">
              <Button
                onClick={() => updateHousehold.mutate()}
                disabled={!householdForm.name.trim() || updateHousehold.isPending}
              >
                {updateHousehold.isPending ? "保存中…" : "保存家庭信息"}
              </Button>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader
            title="家庭成员"
            description="同一家庭内的成员共享账本数据"
            action={
              isOwner ? (
                <Button
                  variant="ghost"
                  className="h-8 px-2 text-xs"
                  onClick={() => setMemberModal(true)}
                >
                  <UserPlus className="h-3.5 w-3.5" />
                  添加成员
                </Button>
              ) : undefined
            }
          />
          {users.isLoading ? (
            <Spinner />
          ) : users.isError ? (
            <div className="p-5">
              <ErrorBanner message={errorMessage(users.error)} />
            </div>
          ) : (
            <ul className="divide-y divide-ink/6">
              {users.data?.map((user) => (
                <li key={user.id} className="flex items-center gap-3 px-5 py-3.5">
                  <span className="grid h-9 w-9 place-items-center rounded-full bg-primary-50 text-xs font-semibold text-primary-700">
                    {user.display_name.slice(0, 1).toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 text-sm font-medium text-ink">
                      <span className="truncate">{user.display_name}</span>
                      {user.id === authUser?.id ? <Badge tone="blue">我</Badge> : null}
                      <Badge tone={user.role === "owner" ? "green" : "slate"}>
                        {user.role === "owner" ? "管理员" : "成员"}
                      </Badge>
                      {!user.is_active ? <Badge tone="amber">已停用</Badge> : null}
                    </p>
                    <p className="truncate text-xs text-ink/40">@{user.username}</p>
                  </div>
                  {isOwner ? (
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        className="h-8 px-2"
                        title="重置密码"
                        onClick={() => {
                          setPasswordTarget(user);
                          setNewPassword("");
                        }}
                      >
                        <KeyRound className="h-3.5 w-3.5" />
                      </Button>
                      {user.id !== authUser?.id ? (
                        <Button
                          variant="ghost"
                          className="h-8 px-2 text-xs"
                          onClick={() =>
                            updateMember.mutate({
                              id: user.id,
                              payload: { is_active: !user.is_active },
                            })
                          }
                        >
                          {user.is_active ? "停用" : "启用"}
                        </Button>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Modal open={memberModal} title="添加家庭成员" onClose={() => setMemberModal(false)}>
        <div className="space-y-4">
          <Field label="用户名">
            <Input
              value={memberForm.username}
              onChange={(event) =>
                setMemberForm((value) => ({ ...value, username: event.target.value }))
              }
              placeholder="字母、数字、下划线"
            />
          </Field>
          <Field label="显示名称">
            <Input
              value={memberForm.display_name}
              onChange={(event) =>
                setMemberForm((value) => ({ ...value, display_name: event.target.value }))
              }
            />
          </Field>
          <Field label="初始密码" hint="至少 8 个字符，成员登录后可自行使用">
            <Input
              type="password"
              value={memberForm.password}
              onChange={(event) =>
                setMemberForm((value) => ({ ...value, password: event.target.value }))
              }
            />
          </Field>
          <Field label="角色">
            <Select
              value={memberForm.role}
              onChange={(event) =>
                setMemberForm((value) => ({
                  ...value,
                  role: event.target.value as "member" | "owner",
                }))
              }
            >
              <option value="member">成员</option>
              <option value="owner">管理员</option>
            </Select>
          </Field>
          {createMember.isError ? (
            <ErrorBanner message={errorMessage(createMember.error)} />
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setMemberModal(false)}>
              取消
            </Button>
            <Button
              disabled={
                !memberForm.username.trim() ||
                !memberForm.display_name.trim() ||
                memberForm.password.length < 8 ||
                createMember.isPending
              }
              onClick={() => createMember.mutate()}
            >
              <Plus className="h-4 w-4" />
              {createMember.isPending ? "添加中…" : "添加成员"}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={Boolean(passwordTarget)}
        title={`重置密码 · ${passwordTarget?.display_name ?? ""}`}
        onClose={() => setPasswordTarget(null)}
      >
        <div className="space-y-4">
          <Field label="新密码" hint="至少 8 个字符">
            <Input
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
            />
          </Field>
          {updateMember.isError ? (
            <ErrorBanner message={errorMessage(updateMember.error)} />
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setPasswordTarget(null)}>
              取消
            </Button>
            <Button
              disabled={newPassword.length < 8 || updateMember.isPending}
              onClick={() => {
                if (passwordTarget) {
                  updateMember.mutate({
                    id: passwordTarget.id,
                    payload: { password: newPassword },
                  });
                }
              }}
            >
              {updateMember.isPending ? "保存中…" : "重置密码"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
