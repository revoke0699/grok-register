import { AtSign, Mail, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";

const EMAIL_PROVIDER_LABELS: Record<string, string> = {
  outlookemail: "Outlook 邮箱池",
  cloudflare: "Cloudflare 邮箱",
  duckmail: "DuckMail",
  yyds: "YYDS 邮箱",
  mailnest: "MailNest",
  cloudmail: "CloudMail",
  icloud: "iCloud 邮箱",
  history: "历史文件",
};

export function emailProviderLabel(provider?: string | null) {
  const value = String(provider || "").trim();
  return value ? EMAIL_PROVIDER_LABELS[value.toLowerCase()] || value : "未知邮箱来源";
}

export function EmailProviderLabel({
  provider,
  className,
}: {
  provider?: string | null;
  className?: string;
}) {
  const raw = String(provider || "").trim();
  return (
    <span
      title={raw || "未记录邮箱来源"}
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-600",
        className,
      )}
    >
      <Mail className="h-3 w-3 shrink-0 text-slate-400" aria-hidden="true" />
      <span className="truncate">{emailProviderLabel(raw)}</span>
    </span>
  );
}

export function EmailProviderIcon({
  provider,
  className,
}: {
  provider?: string | null;
  className?: string;
}) {
  const label = emailProviderLabel(provider);
  return (
    <span
      title={`邮箱来源：${label}`}
      aria-label={`邮箱来源：${label}`}
      className={cn(
        "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-500",
        className,
      )}
    >
      <AtSign className="h-3.5 w-3.5" aria-hidden="true" />
    </span>
  );
}

export function AccountEmailIcon({
  botRisk,
  className,
}: {
  botRisk?: boolean;
  className?: string;
}) {
  if (botRisk) {
    return (
      <span title="该账号被打上机器人标记" className="inline-flex">
        <ShieldAlert
          className={cn("h-4 w-4 shrink-0 text-amber-600", className)}
          aria-label="该账号被打上机器人标记"
        />
      </span>
    );
  }
  return <Mail className={cn("h-4 w-4 shrink-0 text-primary text-sky-600", className)} aria-hidden="true" />;
}

export function AccountEmailLabel({
  email,
  botRisk,
  className,
  emailClassName,
}: {
  email?: string | null;
  botRisk?: boolean;
  className?: string;
  emailClassName?: string;
}) {
  return (
    <div className={cn("flex min-w-0 items-start gap-2", className)}>
      <AccountEmailIcon botRisk={!!botRisk} className="mt-0.5" />
      <div className={cn("min-w-0 break-all font-medium text-slate-950", emailClassName)}>
        {email || "-"}
      </div>
    </div>
  );
}
