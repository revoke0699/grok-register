import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// 与 backend/registration/engine.py 的 FAIL_LABELS 保持一致。
// 未知类型回退成原始值，避免界面出现空标签。
export const FAILURE_TYPE_LABELS: Record<string, string> = {
  domain_rejected: "域名拒绝",
  already_registered: "账号已注册",
  registration_risk: "注册风控",
  code_timeout: "验证码超时",
  code_fill_failed: "验证码填写失败",
  browser: "浏览器断开",
  cpa: "CPA失败",
  stuck_retry: "流程卡住",
  sso_timeout: "SSO超时",
  invalid_credentials: "账号密码错误",
  other: "其它",
};

export function failureTypeLabel(value?: string | null) {
  const key = String(value || "").trim();
  if (!key) return "";
  return FAILURE_TYPE_LABELS[key] || key;
}

export function formatDuration(seconds?: number | null) {
  const value = Number(seconds || 0);
  if (!value || value <= 0) return "-";
  if (value < 60) return `${value.toFixed(1)}s`;
  const m = Math.floor(value / 60);
  const s = Math.round(value % 60);
  return `${m}m ${s}s`;
}

export function maskSecret(value?: string | null, show = false) {
  const text = String(value || "");
  if (!text) return "";
  if (show) return text;
  if (text.length <= 4) return "****";
  return `${text.slice(0, 2)}${"*".repeat(Math.min(text.length - 4, 12))}${text.slice(-2)}`;
}

export async function copyText(text: string) {
  const value = String(text || "");
  if (!value) return false;
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = value;
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  }
}
