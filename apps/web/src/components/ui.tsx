import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

import { cn } from "../lib/utils";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "outline";

const buttonStyles: Record<ButtonVariant, string> = {
  primary:
    "bg-primary-600 text-white hover:bg-primary-700 shadow-sm disabled:bg-primary-300",
  secondary: "bg-ink text-white hover:bg-ink/90 disabled:opacity-50",
  ghost: "bg-transparent text-ink/70 hover:bg-ink/5 hover:text-ink",
  danger: "bg-red-50 text-red-700 hover:bg-red-100 border border-red-200",
  outline: "border border-ink/15 bg-white text-ink hover:border-primary-400 hover:text-primary-700",
};

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium transition disabled:cursor-not-allowed",
        buttonStyles[variant],
        className,
      )}
      {...props}
    />
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-11 w-full rounded-xl border border-ink/15 bg-white px-3.5 text-sm text-ink outline-none transition placeholder:text-ink/35 focus:border-primary-500 focus:ring-4 focus:ring-primary-500/10 disabled:bg-ink/5",
        className,
      )}
      {...props}
    />
  );
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-11 w-full appearance-none rounded-xl border border-ink/15 bg-white px-3.5 text-sm text-ink outline-none transition focus:border-primary-500 focus:ring-4 focus:ring-primary-500/10",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "min-h-24 w-full rounded-xl border border-ink/15 bg-white px-3.5 py-3 text-sm text-ink outline-none transition placeholder:text-ink/35 focus:border-primary-500 focus:ring-4 focus:ring-primary-500/10",
        className,
      )}
      {...props}
    />
  );
}

export function Label({ className, ...props }: HTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn("mb-1.5 block text-xs font-semibold tracking-wide text-ink/55", className)}
      {...props}
    />
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div>
      <Label>{label}</Label>
      {children}
      {hint ? <p className="mt-1.5 text-xs text-ink/45">{hint}</p> : null}
    </div>
  );
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-ink/10 bg-white/90 shadow-card backdrop-blur",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-ink/8 px-5 py-4">
      <div>
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {description ? <p className="mt-0.5 text-xs text-ink/50">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

type BadgeTone = "green" | "red" | "amber" | "slate" | "blue";

const badgeStyles: Record<BadgeTone, string> = {
  green: "bg-primary-50 text-primary-700 border-primary-200",
  red: "bg-red-50 text-red-700 border-red-200",
  amber: "bg-amber-50 text-amber-700 border-amber-200",
  slate: "bg-ink/5 text-ink/60 border-ink/10",
  blue: "bg-blue-50 text-blue-700 border-blue-200",
};

export function Badge({
  tone = "slate",
  children,
  className,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium",
        badgeStyles[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow ? (
          <p className="mb-1 text-xs font-semibold uppercase tracking-[0.2em] text-primary-700">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {description ? <p className="mt-1 text-sm text-ink/55">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 h-10 w-10 rounded-2xl bg-primary-50" />
      <p className="text-sm font-medium text-ink">{title}</p>
      {description ? <p className="mt-1 max-w-sm text-xs text-ink/50">{description}</p> : null}
    </div>
  );
}

export function Spinner({ label = "加载中…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-14 text-sm text-ink/50">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink/15 border-t-primary-600" />
      {label}
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {message}
    </div>
  );
}

export function SuccessBanner({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-primary-200 bg-primary-50 px-4 py-3 text-sm text-primary-800">
      {message}
    </div>
  );
}

export function Modal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/30 p-0 backdrop-blur-sm sm:items-center sm:p-6">
      <div className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-3xl border border-ink/10 bg-white p-5 shadow-2xl sm:rounded-3xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          <Button variant="ghost" className="h-9 px-3" onClick={onClose}>
            关闭
          </Button>
        </div>
        {children}
      </div>
    </div>
  );
}
