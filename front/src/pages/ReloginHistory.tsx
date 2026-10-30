import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, Copy, History, Search, Trash2, XCircle } from "lucide-react";
import { Badge, Button, Card, EmptyState, Input, PageHeader, PaginationBar, Select, Toast } from "@/components/ui";
import { AccountPageContext } from "@/components/AccountPageContext";
import { buildReloginReportText, reloginSsoCheckLabel } from "@/components/ReloginReportDialog";
import {
  clearReloginHistory,
  loadReloginHistory,
  removeReloginHistory,
  type ReloginHistoryEntry,
} from "@/lib/reloginHistory";
import { copyText } from "@/lib/utils";
import { api, type AccountRecord, type ReloginItem } from "@/lib/api";

function formatWhen(value: number | null) {
  return value ? new Date(value * 1000).toLocaleString() : "时间未知";
}

function enrichReloginItem(item: ReloginItem, account?: AccountRecord): ReloginItem {
  const extra = account?.extra && typeof account.extra === "object" ? account.extra : {};
  const rawDiagnostics = extra.relogin_diagnostics;
  const diagnostics = rawDiagnostics && typeof rawDiagnostics === "object"
    ? rawDiagnostics as Record<string, unknown>
    : {};
  const value = (key: string) => String(diagnostics[key] || "");
  const screenshotName = item.screenshot_name || value("screenshot_name");
  const immutableScreenshotUrl = screenshotName
    ? `/api/accounts/${item.account_id}/relogin-screenshots/${encodeURIComponent(screenshotName)}`
    : "";
  return {
    ...item,
    error: item.error || String(extra.relogin_error || ""),
    stage: item.stage || value("stage"),
    error_type: item.error_type || value("error_type"),
    failure_type: item.failure_type || value("failure_type") || (String(extra.relogin_error || "").includes("账号或密码错误") ? "invalid_credentials" : ""),
    url: item.url || value("url"),
    page_title: item.page_title || value("page_title"),
    visible_error: item.visible_error || value("visible_error"),
    page_text: item.page_text || value("page_text"),
    controls: item.controls || value("controls"),
    traceback: item.traceback || value("traceback"),
    screenshot_name: screenshotName,
    captured_at: item.captured_at || value("captured_at"),
    screenshot_url: item.screenshot_url || immutableScreenshotUrl || account?.screenshot_url || "",
  };
}

export function ReloginHistoryPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [entries, setEntries] = useState<ReloginHistoryEntry[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "success" | "failed">("all");
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize, setHistoryPageSize] = useState(20);
  const [reportPage, setReportPage] = useState(1);
  const [reportPageSize, setReportPageSize] = useState(20);
  const [accountSnapshots, setAccountSnapshots] = useState<Record<number, AccountRecord>>({});
  const [toast, setToast] = useState("");

  useEffect(() => {
    void loadReloginHistory().then(setEntries);
  }, []);

  const selected = entries.find((entry) => entry.run_id === runId) || null;
  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return entries.filter((entry) => {
      if (filter === "success" && entry.failed_count) return false;
      if (filter === "failed" && !entry.failed_count) return false;
      if (!keyword) return true;
      return entry.items.some((item) => item.email.toLowerCase().includes(keyword));
    });
  }, [entries, filter, query]);
  const safeHistoryPage = Math.min(historyPage, Math.max(1, Math.ceil(filtered.length / historyPageSize)));
  const pagedEntries = filtered.slice((safeHistoryPage - 1) * historyPageSize, safeHistoryPage * historyPageSize);
  const reportItems = useMemo(
    () => selected ? [...selected.items].sort((a, b) => (a.status === "failed" ? -1 : 1) - (b.status === "failed" ? -1 : 1)) : [],
    [selected]
  );
  const safeReportPage = Math.min(reportPage, Math.max(1, Math.ceil(reportItems.length / reportPageSize)));
  const pagedReportItems = reportItems.slice((safeReportPage - 1) * reportPageSize, safeReportPage * reportPageSize);
  const reportPageKey = pagedReportItems.map((item) => item.account_id).join(",");

  useEffect(() => { setHistoryPage(1); }, [query, filter]);
  useEffect(() => { setReportPage(1); }, [runId]);
  useEffect(() => {
    const ids = pagedReportItems
      .filter((item) => item.status === "failed" && !accountSnapshots[item.account_id])
      .map((item) => item.account_id);
    if (!ids.length) return;
    let active = true;
    void Promise.all(ids.map((id) => api.account(id).then((result) => result.item).catch(() => null))).then((rows) => {
      if (!active) return;
      setAccountSnapshots((previous) => {
        const next = { ...previous };
        for (const row of rows) if (row) next[row.id] = row;
        return next;
      });
    });
    return () => { active = false; };
  }, [reportPageKey]);

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2200);
  };

  const remove = async (id: string) => {
    if (!window.confirm("删除这次重新登录历史？")) return;
    setEntries(await removeReloginHistory(id));
    if (runId === id) navigate("/accounts/relogin/history", { replace: true });
  };

  if (runId) {
    return (
      <div className="space-y-5">
        <AccountPageContext crumbs={[{ label: "重新登录", to: "/accounts/relogin" }, { label: "登录历史", to: "/accounts/relogin/history" }, { label: "报告" }]} backTo="/accounts/relogin/history" backLabel="返回历史列表" />
        {!selected ? (
          <Card className="p-5">
            <EmptyState title="报告不存在" description="该记录可能已被删除，或者浏览器数据已被清理。" />
          </Card>
        ) : (
          <>
            <PageHeader
              title="重新登录报告"
              description={`完成于 ${formatWhen(selected.finished_at)}`}
              actions={
                <>
                  <Button
                    variant="outline"
                    onClick={async () => {
                      const ok = await copyText(buildReloginReportText(selected));
                      notify(ok ? "报告已复制" : "复制失败");
                    }}
                  >
                    <Copy className="h-4 w-4" aria-hidden="true" />
                    复制报告
                  </Button>
                  <Button variant="outline" className="text-red-700" onClick={() => void remove(selected.run_id)}>
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                    删除
                  </Button>
                </>
              }
            />
            <section className="grid gap-3 sm:grid-cols-3">
              {[
                ["账号总数", selected.total_count, "text-slate-950"],
                ["成功", selected.success_count, "text-emerald-700"],
                ["失败", selected.failed_count, "text-red-700"],
              ].map(([label, value, tone]) => (
                <Card key={String(label)} className="p-4">
                  <div className="text-xs text-slate-500">{label}</div>
                  <div className={`mt-2 text-2xl font-semibold tabular-nums ${tone}`}>{value}</div>
                </Card>
              ))}
            </section>
            <Card className="overflow-hidden">
              <div className="border-b border-slate-200 px-4 py-4 sm:px-5">
                <h2 className="font-semibold text-slate-950">账号结果</h2>
                <p className="mt-1 text-xs text-slate-500">失败记录优先展示，便于快速定位。</p>
              </div>
              <div className="divide-y divide-slate-100">
                {pagedReportItems.map((item) => {
                  const detailItem = enrichReloginItem(item, accountSnapshots[item.account_id]);
                  return (
                    <div key={detailItem.account_id} className="flex items-start gap-3 px-4 py-3 sm:px-5">
                      {detailItem.status === "success" ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
                      ) : (
                        <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" aria-hidden="true" />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="break-all text-sm font-medium text-slate-900">{detailItem.email || `账号 #${detailItem.account_id}`}</div>
                        <div className={`mt-1 break-all text-xs ${detailItem.status === "failed" ? "text-red-700" : "text-slate-500"}`}>
                          {detailItem.status === "failed"
                            ? (detailItem.failure_type === "invalid_credentials"
                              ? "账号或密码错误，不是 SSO 异常"
                              : detailItem.error || "未知错误")
                            : reloginSsoCheckLabel(detailItem) || "重新登录成功"}
                        </div>
                        {detailItem.status === "failed" && (detailItem.stage || detailItem.error_type || detailItem.url || detailItem.visible_error) ? (
                          <div className="mt-3 grid gap-2 rounded-lg border border-red-100 bg-red-50/50 p-3 text-xs sm:grid-cols-2">
                            {detailItem.stage ? <div><span className="text-slate-500">失败阶段</span><div className="mt-0.5 font-medium text-slate-800">{detailItem.stage}</div></div> : null}
                            {detailItem.failure_type === "invalid_credentials" ? <div><span className="text-slate-500">结论</span><div className="mt-0.5 text-red-700">账号或密码错误，不是 SSO 异常</div></div> : null}
                            {detailItem.error_type ? <div><span className="text-slate-500">异常类型</span><div className="mt-0.5 font-mono text-slate-800">{detailItem.error_type}</div></div> : null}
                            {detailItem.visible_error && detailItem.visible_error !== detailItem.error ? <div className="sm:col-span-2"><span className="text-slate-500">页面错误</span><div className="mt-0.5 break-words text-red-700">{detailItem.visible_error}</div></div> : null}
                            {detailItem.url ? <div className="sm:col-span-2"><span className="text-slate-500">失败页面</span><div className="mt-0.5 break-all font-mono text-slate-700">{detailItem.url}</div></div> : null}
                          </div>
                        ) : null}
                        {detailItem.status === "failed" && (detailItem.controls || detailItem.page_text || detailItem.traceback || detailItem.screenshot_url) ? (
                          <div className="mt-2 space-y-2">
                            {detailItem.screenshot_url ? (
                              <div className="flex flex-wrap items-center gap-2 text-xs">
                                <a href={detailItem.screenshot_url} target="_blank" rel="noreferrer" className="font-medium text-sky-600 hover:underline">查看失败截图</a>
                                {detailItem.captured_at ? <span className="text-slate-400">截图时间：{new Date(detailItem.captured_at).toLocaleString()}</span> : detailItem.screenshot_name ? <span className="text-slate-400">{detailItem.screenshot_name}</span> : null}
                              </div>
                            ) : null}
                            {detailItem.controls || detailItem.page_text ? (
                              <details className="rounded-lg border border-slate-200 bg-slate-50">
                                <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-slate-700">查看页面元素与文本</summary>
                                <div className="space-y-2 border-t border-slate-200 p-3 text-xs leading-5 text-slate-600">
                                  {detailItem.controls ? <div><strong className="text-slate-800">可见控件：</strong>{detailItem.controls}</div> : null}
                                  {detailItem.page_text ? <div className="whitespace-pre-wrap break-words"><strong className="text-slate-800">页面文本：</strong>{detailItem.page_text}</div> : null}
                                </div>
                              </details>
                            ) : null}
                            {detailItem.traceback ? (
                              <details className="rounded-lg border border-slate-200 bg-slate-50">
                                <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-slate-700">查看异常堆栈</summary>
                                <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-slate-200 p-3 font-mono text-[11px] leading-5 text-slate-600">{detailItem.traceback}</pre>
                              </details>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                      <Badge variant={detailItem.status === "success" ? "success" : "destructive"}>
                        {detailItem.status === "success" ? "成功" : "失败"}
                      </Badge>
                    </div>
                  );
                })}
              </div>
              {reportItems.length > 0 ? (
                <PaginationBar
                  page={safeReportPage}
                  pageSize={reportPageSize}
                  total={reportItems.length}
                  onPageChange={setReportPage}
                  onPageSizeChange={(size) => { setReportPageSize(size); setReportPage(1); }}
                />
              ) : null}
            </Card>
          </>
        )}
        <Toast message={toast} />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <AccountPageContext crumbs={[{ label: "重新登录", to: "/accounts/relogin" }, { label: "登录历史" }]} />
      <PageHeader
        title="登录历史"
        description="重新登录报告保存在当前浏览器 IndexedDB，可随时查看、复制或删除。"
        actions={
          <Button
            variant="outline"
            className="text-red-700"
            disabled={!entries.length}
            onClick={async () => {
              if (!window.confirm("清空全部重新登录历史？")) return;
              setEntries(await clearReloginHistory());
            }}
          >
            <Trash2 className="h-4 w-4" aria-hidden="true" />
            清空历史
          </Button>
        }
      />

      <Card className="p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-slate-400" aria-hidden="true" />
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索报告中的邮箱" className="pl-9" />
          </div>
          <Select value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)} className="md:w-44" aria-label="筛选登录历史">
            <option value="all">全部报告</option>
            <option value="success">完全成功</option>
            <option value="failed">包含失败</option>
          </Select>
        </div>
      </Card>

      {filtered.length ? (
        <section className="grid gap-3 xl:grid-cols-2">
          {pagedEntries.map((entry) => (
            <Card key={entry.run_id} className="p-4 sm:p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
                    <History className="h-4 w-4 text-sky-600" aria-hidden="true" />
                    {formatWhen(entry.finished_at)}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <Badge variant="secondary">总数 {entry.total_count}</Badge>
                    <Badge variant="success">成功 {entry.success_count}</Badge>
                    {entry.failed_count ? <Badge variant="destructive">失败 {entry.failed_count}</Badge> : null}
                  </div>
                </div>
                <Button size="icon" variant="ghost" className="h-9 w-9 text-red-700" onClick={() => void remove(entry.run_id)}>
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>
              <div className="mt-4 flex gap-2 border-t border-slate-100 pt-3">
                <Link
                  to={`/accounts/relogin/history/${entry.run_id}`}
                  className="inline-flex min-h-9 flex-1 items-center justify-center rounded-lg bg-slate-900 px-3 text-xs font-medium text-white hover:bg-slate-800"
                >
                  查看报告
                </Link>
              </div>
            </Card>
          ))}
        </section>
      ) : (
        <Card className="p-4">
          <EmptyState title="暂无登录历史" description="完成一次重新登录后，本次报告会自动记录在这里。" />
        </Card>
      )}
      {filtered.length > 0 ? (
        <Card className="overflow-hidden">
          <PaginationBar
            page={safeHistoryPage}
            pageSize={historyPageSize}
            total={filtered.length}
            onPageChange={setHistoryPage}
            onPageSizeChange={(size) => { setHistoryPageSize(size); setHistoryPage(1); }}
          />
        </Card>
      ) : null}
      <Toast message={toast} />
    </div>
  );
}
