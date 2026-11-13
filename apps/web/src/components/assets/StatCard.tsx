import type { LucideIcon } from "lucide-react";

import { cn } from "../../lib/utils";

interface StatCardProps {
  label: string;
  value: string;
  hint?: string;
  hintTone?: string;
  icon: LucideIcon;
  tone?: string;
}

export function StatCard({ label, value, hint, hintTone, icon: Icon, tone }: StatCardProps) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-slate-500">{label}</p>
        {Icon ? (
          <span className={cn("flex h-8 w-8 items-center justify-center rounded-lg", tone)}>
            <Icon className="h-4 w-4" />
          </span>
        ) : null}
      </div>
      <p className="mt-2 truncate text-xl font-semibold tracking-tight text-slate-900" title={value}>
        {value}
      </p>
      {hint ? <p className={cn("mt-1 text-xs", hintTone ?? "text-slate-500")}>{hint}</p> : null}
    </div>
  );
}
