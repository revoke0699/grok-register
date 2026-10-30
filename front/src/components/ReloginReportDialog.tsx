import { useMemo } from "react";
import { CheckCircle2, Clock3, Copy, XCircle, X } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import type { ReloginItem } from "@/lib/api";

/** 只取渲染所需字段，便于同时接受实时 ReloginStatus 与历史条目。 */
export type ReloginReportLike = {
  finished_at?: number | null;
  total_count: number;
  success_count: number;
  failed_count: number;
  items: ReloginItem[];
};

function itemLabel(item: ReloginItem) {
  return item.email || `账号 #${item.account_id}`;
}

export function reloginSsoCheckLabel(item: ReloginItem) {
  const source = item.bot_flag_source;
  if (item.sso_check_status === "clean") return "历史 SSO 检查：正常";
  if (item.sso_check_status === "flagged") {
    return `历史 SSO 检查：异常（botFlagSource=${source ?? "-"}）`;
  }
  if (item.sso_check_status === "unknown") return "历史 SSO 检查：结论未知";
  if (item.sso_check_status === "failed") return "历史 SSO 检查失败";
  return "";
}

/** 复制用纯文本。按后端原始顺序（即用户选择顺序），与弹窗内的排序刻意不同。 */
export function buildReloginReportText(report: ReloginReportLike) {
  const items = report.items ?? [];
  // finished_at 是后端 time.time() 的秒级浮点，需要乘 1000 才能进 Date。
  const when = report.finished_at ? new Date(report.finished_at * 1000).toLocaleString() : "";
  const head = [
    "重新登录结果报告",
    when,
    `总数 ${report.total_count} / 成功 ${report.success_count} / 失败 ${report.failed_count}`,
  ].filter(Boolean);
  const lines = items.map((item) => {
    const riskLabel = reloginSsoCheckLabel(item);
    if (item.status === "success") {
      return [
        `[成功] ${itemLabel(item)}`,
        riskLabel ? `  ${riskLabel}` : "",
        item.sso_check_error ? `  检查说明：${item.sso_check_error}` : "",
      ].filter(Boolean).join("\n");
    }
    if (item.status === "pending") return `[未执行] ${itemLabel(item)}`;
    return [
      `[失败] ${itemLabel(item)}：${item.error || "未知原因"}`,
      riskLabel ? `  ${riskLabel}` : "",
      item.sso_check_error ? `  检查说明：${item.sso_check_error}` : "",
      item.stage ? `  阶段：${item.stage}` : "",
      item.failure_type === "invalid_credentials" ? "  结论：账号或密码错误，不是 SSO 异常" : "",
      item.error_type ? `  异常类型：${item.error_type}` : "",
      item.visible_error && item.visible_error !== item.error ? `  页面错误：${item.visible_error}` : "",
      item.url ? `  页面地址：${item.url}` : "",
      item.controls ? `  页面控件：${item.controls}` : "",
      item.page_text ? `  页面文本：${item.page_text}` : "",
      item.captured_at ? `  截图时间：${new Date(item.captured_at).toLocaleString()}` : "",
      item.screenshot_url ? `  失败截图：${item.screenshot_url}` : "",
      item.traceback ? `  异常堆栈：\n${item.traceback}` : "",
    ].filter(Boolean).join("\n");
  });
  return [...head, "", ...lines].join("\n");
}

const ORDER: Record<string, number> = { failed: 0, pending: 1, success: 2 };

export function ReloginReportDialog({
  report,
  title,
  onClose,
  onCopy,
}: {
  report: ReloginReportLike;
  title?: string;
  onClose: () => void;
  onCopy: (text: string) => void;
}) {
  // 失败置顶，便于处理；复制文本仍保持原始顺序。
  const items = useMemo(() => {
    const list = [...(report.items ?? [])];
    list.sort((a, b) => (ORDER[a.status] ?? 3) - (ORDER[b.status] ?? 3));
    return list;
  }, [report.items]);

  return (
    <div
      className="fixed inset-0 z-[110] flex items-end bg-slate-950/55 sm:items-center sm:justify-center sm:p-6"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="relogin-report-title"
        className="w-full overflow-hidden rounded-t-3xl bg-card shadow-2xl sm:max-w-xl sm:rounded-3xl"
      >
        <div className="mx-auto mt-2 h-1.5 w-12 rounded-full bg-slate-300 sm:hidden" />
        <header className="flex items-start justify-between gap-3 border-b px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <h2 id="relogin-report-title" className="font-semibold text-foreground">
              {title ?? (report.total_count > 1 ? "批量重新登录报告" : "重新登录报告")}
            </h2>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Badge variant="secondary">总数 {report.total_count}</Badge>
              <Badge variant="success">成功 {report.success_count}</Badge>
              <Badge variant="destructive">失败 {report.failed_count}</Badge>
            </div>
          </div>
          <Button
            size="icon"
            variant="ghost"
            className="shrink-0"
            onClick={onClose}
            aria-label="关闭重新登录报告"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </Button>
        </header>

        <ul className="max-h-[55vh] divide-y overflow-y-auto px-4 sm:px-5">
          {items.map((item) => (
            <li key={item.account_id} className="flex items-start gap-3 py-3">
              {item.status === "success" ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
              ) : item.status === "failed" ? (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" aria-hidden="true" />
              ) : (
                <Clock3 className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              )}
              <div className="min-w-0">
                <div className="break-all text-sm font-medium text-foreground">{itemLabel(item)}</div>
                {item.status === "failed" ? (
                  <div className="mt-0.5 break-all text-xs leading-5 text-red-700">
                    {item.error || "未知原因"}
                  </div>
                ) : (
                  <div className="mt-0.5 text-xs leading-5 text-muted-foreground">
                    {item.status === "success" ? "成功" : "未执行"}
                  </div>
                )}
                {reloginSsoCheckLabel(item) ? (
                  <div className={`mt-1 text-xs ${item.sso_check_status === "flagged" ? "text-amber-700" : item.sso_check_status === "clean" ? "text-emerald-700" : "text-slate-500"}`}>
                    {reloginSsoCheckLabel(item)}
                  </div>
                ) : null}
              </div>
            </li>
          ))}
        </ul>

        <footer className="flex gap-2 border-t px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-3 sm:px-5 sm:pb-4">
          <Button
            variant="outline"
            className="flex-1"
            onClick={() => onCopy(buildReloginReportText(report))}
          >
            <Copy className="h-4 w-4" aria-hidden="true" />
            复制
          </Button>
          <Button className="flex-1" onClick={onClose}>
            关闭
          </Button>
        </footer>
      </section>
    </div>
  );
}
