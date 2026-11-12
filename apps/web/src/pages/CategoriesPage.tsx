import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { categoriesApi } from "../api/endpoints";
import type { Category } from "../api/types";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  Spinner,
  SuccessBanner,
} from "../components/ui";
import { useCategories } from "../hooks/useReference";
import { errorMessage } from "../lib/utils";

interface CategoryForm {
  name: string;
  category_type: "income" | "expense";
  parent_id: string;
  sort_order: string;
  is_active: boolean;
}

export function CategoriesPage() {
  const queryClient = useQueryClient();
  const categories = useCategories();
  const [message, setMessage] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Category | null>(null);
  const [form, setForm] = useState<CategoryForm>({
    name: "",
    category_type: "expense",
    parent_id: "",
    sort_order: "0",
    is_active: true,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["categories"] });
    await queryClient.invalidateQueries({ queryKey: ["statistics"] });
    await queryClient.invalidateQueries({ queryKey: ["transactions"] });
  };

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: form.name.trim(),
        category_type: form.category_type,
        parent_id: form.parent_id || null,
        sort_order: Number(form.sort_order) || 0,
        is_active: form.is_active,
      };
      return editing ? categoriesApi.update(editing.id, payload) : categoriesApi.create(payload);
    },
    onSuccess: async () => {
      setModalOpen(false);
      setEditing(null);
      setMessage(editing ? "分类已更新" : "分类已创建");
      await refresh();
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => categoriesApi.remove(id),
    onSuccess: async () => {
      setMessage("分类已删除");
      await refresh();
    },
  });

  function openCreate(type: "income" | "expense") {
    setEditing(null);
    setForm({
      name: "",
      category_type: type,
      parent_id: "",
      sort_order: "0",
      is_active: true,
    });
    setModalOpen(true);
  }

  function openEdit(category: Category) {
    setEditing(category);
    setForm({
      name: category.name,
      category_type: category.category_type,
      parent_id: category.parent_id ?? "",
      sort_order: String(category.sort_order),
      is_active: category.is_active,
    });
    setModalOpen(true);
  }

  const mutationError = save.error ?? remove.error;
  const groups = (["income", "expense"] as const).map((type) => ({
    type,
    label: type === "income" ? "收入分类" : "支出分类",
    categories: (categories.data ?? [])
      .filter((category) => category.category_type === type)
      .sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)),
  }));

  return (
    <div>
      <PageHeader
        eyebrow="Categories"
        title="分类"
        description="收支分类是统计口径的基础；停用后不再出现在新增记录中。"
        action={
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => openCreate("income")}>
              <Plus className="h-4 w-4" />
              收入分类
            </Button>
            <Button onClick={() => openCreate("expense")}>
              <Plus className="h-4 w-4" />
              支出分类
            </Button>
          </div>
        }
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

      {categories.isLoading ? (
        <Spinner />
      ) : categories.isError ? (
        <ErrorBanner message={errorMessage(categories.error)} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          {groups.map((group) => (
            <Card key={group.type}>
              <CardHeader
                title={group.label}
                description={`${group.categories.length} 个分类`}
                action={
                  <Button
                    variant="ghost"
                    className="h-8 px-2 text-xs"
                    onClick={() => openCreate(group.type)}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    添加
                  </Button>
                }
              />
              {group.categories.length ? (
                <ul className="divide-y divide-ink/6">
                  {group.categories.map((category) => (
                    <li key={category.id} className="flex items-center gap-3 px-5 py-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-ink">
                            {category.name}
                          </span>
                          {category.parent_id ? <Badge tone="slate">子分类</Badge> : null}
                          {!category.is_active ? <Badge tone="amber">已停用</Badge> : null}
                        </div>
                        <p className="mt-0.5 text-xs text-ink/40">
                          排序 {category.sort_order}
                          {category.icon ? ` · 图标 ${category.icon}` : ""}
                        </p>
                      </div>
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          className="h-8 px-2"
                          title="编辑"
                          onClick={() => openEdit(category)}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          className="h-8 px-2 text-red-600"
                          title="删除"
                          onClick={() => {
                            if (window.confirm(`确认删除分类「${category.name}」？`)) {
                              remove.mutate(category.id);
                            }
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title={`暂无${group.label}`} description="点击右上角添加分类。" />
              )}
            </Card>
          ))}
        </div>
      )}

      <Modal
        open={modalOpen}
        title={editing ? "编辑分类" : "新增分类"}
        onClose={() => {
          setModalOpen(false);
          setEditing(null);
        }}
      >
        <div className="space-y-4">
          <Field label="分类名称">
            <Input
              value={form.name}
              onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
              placeholder="例如 餐饮"
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="类型">
              <Select
                value={form.category_type}
                onChange={(event) =>
                  setForm((value) => ({
                    ...value,
                    category_type: event.target.value as "income" | "expense",
                    parent_id: "",
                  }))
                }
              >
                <option value="expense">支出</option>
                <option value="income">收入</option>
              </Select>
            </Field>
            <Field label="排序">
              <Input
                type="number"
                value={form.sort_order}
                onChange={(event) =>
                  setForm((value) => ({ ...value, sort_order: event.target.value }))
                }
              />
            </Field>
          </div>
          <Field label="父分类" hint="可选，用于二级分类">
            <Select
              value={form.parent_id}
              onChange={(event) => setForm((value) => ({ ...value, parent_id: event.target.value }))}
            >
              <option value="">无（一级分类）</option>
              {(categories.data ?? [])
                .filter(
                  (category) =>
                    category.category_type === form.category_type &&
                    !category.parent_id &&
                    category.id !== editing?.id,
                )
                .map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
            </Select>
          </Field>
          <Field label="状态">
            <Select
              value={form.is_active ? "active" : "inactive"}
              onChange={(event) =>
                setForm((value) => ({ ...value, is_active: event.target.value === "active" }))
              }
            >
              <option value="active">启用</option>
              <option value="inactive">停用</option>
            </Select>
          </Field>

          {save.isError ? <ErrorBanner message={errorMessage(save.error)} /> : null}

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setModalOpen(false)}>
              取消
            </Button>
            <Button disabled={!form.name.trim() || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? "保存中…" : "保存"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
