import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, History, ListChecks, Loader2, RefreshCcw, Search, ShieldAlert, Square, TerminalSquare, Users, X, XCircle } from "lucide-react";
import { AccountEmailLabel, EmailProviderIcon, EmailProviderLabel } from "@/components/AccountEmailIcon";
import { AccountPageContext } from "@/components/AccountPageContext";
import { AccountFilterBar, AccountSelectionToolbar } from "@/components/AccountTableToolbar";
import { LiveLogBoard } from "@/components/LiveLogBoard";
import { reloginSsoCheckLabel } from "@/components/ReloginReportDialog";
import { Badge, Button, Card, EmptyState, Input, PageHeader, PaginationBar, Select, Toast } from "@/components/ui";
import { api, type AccountRecord, type LogItem, type ReloginItem, type ReloginStatus } from "@/lib/api";
import { appendReloginHistory } from "@/lib/reloginHistory";

const RELOGIN_RESULT_PAGE_SIZE = 20;

function accountRiskStatus(item: AccountRecord) {
  if (item.bot_risk) return { label: "异常", variant: "destructive" as const };
  const source = item.sso_risk_check?.bot_flag_source;
  if (source === 0 || source === "0") return { label: "正常", variant: "success" as const };
  if (item.sso_risk_check) return { label: "未知", variant: "warning" as const };
  return { label: "未检查", variant: "secondary" as const };
}

function reloginOutcome(item: AccountRecord) {
  if (!item.email || !item.password) return { label: "缺少凭据", variant: "warning" as const };
  const value = String(item.extra?.relogin_status || "");
  if (value === "success") return { label: "重登成功", variant: "success" as const };
  if (value) return { label: value, variant: "warning" as const };
  return { label: "未执行", variant: "secondary" as const };
}

function ReloginResultList({
  items,
  botRiskByAccountId,
}: {
  items: ReloginItem[];
  botRiskByAccountId: ReadonlyMap<number, boolean>;
}) {
  return (
    <div className="divide-y divide-slate-100">
      {items.map((item) => (
        <div key={item.account_id} className="flex items-start gap-3 px-4 py-3 sm:px-5">
          {item.status === "success" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" /> : item.status === "failed" ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" aria-hidden="true" /> : <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-slate-400" aria-hidden="true" />}
          <div className="min-w-0 flex-1">
            <AccountEmailLabel
              email={item.email || `账号 #${item.account_id}`}
              botRisk={item.sso_check_status === "flagged" || !!botRiskByAccountId.get(item.account_id)}
              emailClassName="text-sm text-slate-900"
            />
            {item.sso_check_status ? (
              <div className="mt-1">
                <Badge variant={item.sso_check_status === "flagged" ? "destructive" : item.sso_check_status === "clean" ? "success" : "warning"}>
                  {item.sso_check_status === "flagged" ? <ShieldAlert className="mr-1 h-3 w-3" aria-hidden="true" /> : null}
                  {reloginSsoCheckLabel(item)}
                </Badge>
              </div>
            ) : botRiskByAccountId.get(item.account_id) ? (
              <div className="mt-1">
                <Badge variant="warning">
                  <ShieldAlert className="mr-1 h-3 w-3" aria-hidden="true" />
                  风控标记
                </Badge>
              </div>
            ) : null}
            {item.sso_check_error && item.sso_check_error !== item.error ? (
              <div className="mt-1 break-all text-xs text-amber-700">SSO 检查：{item.sso_check_error}</div>
            ) : null}
            {item.failure_type === "invalid_credentials" || /账号或密码错误|Wrong email address or password/i.test(item.error || item.visible_error || "") ? (
              <div className="mt-1"><Badge variant="destructive">账号或密码错误，不是 SSO 异常</Badge></div>
            ) : null}
            {item.error ? <div className="mt-1 break-all text-xs text-red-700">{item.error}</div> : null}
            {item.status === "failed" && (item.stage || item.error_type || item.url) ? (
              <div className="mt-2 space-y-1 rounded-lg bg-red-50 p-2 text-xs text-slate-600">
                {item.stage ? <div><strong className="text-slate-800">阶段：</strong>{item.stage}</div> : null}
                {item.error_type ? <div><strong className="text-slate-800">类型：</strong>{item.error_type}</div> : null}
                {item.url ? <div className="break-all"><strong className="text-slate-800">页面：</strong>{item.url}</div> : null}
                {item.screenshot_url ? <div className="flex flex-wrap items-center gap-2"><a href={item.screenshot_url} target="_blank" rel="noreferrer" className="font-medium text-sky-600 hover:underline">查看失败截图</a>{item.captured_at ? <span className="text-slate-400">{new Date(item.captured_at).toLocaleString()}</span> : null}</div> : null}
              </div>
            ) : null}
          </div>
          <Badge variant={item.status === "success" ? "success" : item.status === "failed" ? "destructive" : "secondary"}>{item.status === "success" ? "成功" : item.status === "failed" ? "失败" : "等待"}</Badge>
        </div>
      ))}
    </div>
  );
}

function ReloginResultsDrawer({
  status,
  items,
  page,
  botRiskByAccountId,
  onPageChange,
  onClose,
}: {
  status: ReloginStatus;
  items: ReloginItem[];
  page: number;
  botRiskByAccountId: ReadonlyMap<number, boolean>;
  onPageChange: (page: number) => void;
  onClose: () => void;
}) {
  const totalPages = Math.max(1, Math.ceil(status.items.length / RELOGIN_RESULT_PAGE_SIZE));
  return (
    <div className="fixed inset-0 z-[100] flex justify-end">
      <button
        type="button"
        tabIndex={-1}
        className="absolute inset-0 bg-slate-950/45"
        aria-label="关闭本次重新登录结果"
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="relogin-results-title"
        aria-describedby="relogin-results-description"
        className="relative flex h-full w-full max-w-4xl flex-col border-l border-slate-200 bg-white shadow-2xl"
      >
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-200 px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 id="relogin-results-title" className="font-semibold text-slate-950">本次重新登录结果</h2>
              <Badge variant={status.running ? "default" : "success"}>{status.running ? "执行中" : "已完成"}</Badge>
            </div>
            <p id="relogin-results-description" className="mt-1 text-xs text-slate-500">
              共 {status.items.length} 个账号 · 每页 20 条 · 第 {page} / {totalPages} 页
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge variant="secondary">已完成 {status.completed_count}</Badge>
              <Badge variant="success">成功 {status.success_count}</Badge>
              <Badge variant="destructive">失败 {status.failed_count}</Badge>
            </div>
          </div>
          <Button size="icon" variant="ghost" className="shrink-0" onClick={onClose} aria-label="关闭本次重新登录结果">
            <X className="h-5 w-5" aria-hidden="true" />
          </Button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <ReloginResultList items={items} botRiskByAccountId={botRiskByAccountId} />
        </div>
        <div className="shrink-0 bg-white pb-[env(safe-area-inset-bottom)]">
          <PaginationBar
            page={page}
            pageSize={RELOGIN_RESULT_PAGE_SIZE}
            total={status.items.length}
            onPageChange={onPageChange}
          />
        </div>
      </aside>
    </div>
  );
}

export function ReloginPage() {
  const [accounts, setAccounts] = useState<AccountRecord[]>([]);
  const [selected, setSelected] = useState<Record<number, boolean>>({});
  const [query, setQuery] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [selectingAll, setSelectingAll] = useState(false);
  const [starting, setStarting] = useState(false);
  const [ssoCheckRunning, setSsoCheckRunning] = useState(false);
  const [status, setStatus] = useState<ReloginStatus | null>(null);
  const [resultPage, setResultPage] = useState(1);
  const [resultsOpen, setResultsOpen] = useState(false);
  const [toast, setToast] = useState<{ message: string; tone?: "default" | "success" | "error" }>({ message: "" });
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [activeTab, setActiveTab] = useState<"accounts" | "logs">("accounts");
  const [stopping, setStopping] = useState(false);
  const recordedRun = useRef("");
  const seenRunIdRef = useRef("");
  const afterLogIdRef = useRef(0);
  const logViewVersionRef = useRef(0);
  const logPollingRef = useRef(false);

  const notify = (message: string, tone: "default" | "success" | "error" = "default") => {
    setToast({ message, tone });
    window.setTimeout(() => setToast({ message: "" }), 2400);
  };

  const loadAccounts = async (targetPage = page, targetQuery = query, targetPageSize = pageSize) => {
    setLoading(true);
    try {
      const result = await api.accounts({
        limit: targetPageSize,
        offset: (targetPage - 1) * targetPageSize,
        q: targetQuery.trim(),
        botRisk: riskFilter || undefined,
      });
      setAccounts(result.items || []);
      setTotal(Number(result.total ?? result.items?.length ?? 0));
      setPage(targetPage);
    } catch (error: any) {
      notify(error.message || "账号加载失败", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSelected({});
      void loadAccounts(1, query);
    }, 280);
    return () => window.clearTimeout(timer);
  }, [query, riskFilter]);

  const refreshReloginLogs = async () => {
    if (logPollingRef.current) return null;
    logPollingRef.current = true;
    const viewVersion = logViewVersionRef.current;
    try {
      const data = await api.reloginLogs(afterLogIdRef.current, 500);
      if (viewVersion !== logViewVersionRef.current) return data.relogin;
      const next = data.relogin;
      if (next.run_id && next.run_id !== seenRunIdRef.current) {
        if (seenRunIdRef.current) setLogs([]);
        seenRunIdRef.current = next.run_id;
      }
      setStatus(next);
      const freshLogs = (data.logs || []).filter((item) => item.id > afterLogIdRef.current);
      if (freshLogs.length) {
        setLogs((prev) => [...prev, ...freshLogs].slice(-2000));
        afterLogIdRef.current = freshLogs[freshLogs.length - 1].id;
      }
      return next;
    } catch {
      return null;
    } finally {
      logPollingRef.current = false;
    }
  };

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await refreshReloginLogs();
        if (!active) return;
        if (next?.running) {
          timer = window.setTimeout(poll, 1200);
          return;
        }
        if (next?.run_id && recordedRun.current !== next.run_id) {
          await appendReloginHistory(next);
          recordedRun.current = next.run_id;
          if (next.finished_at) void loadAccounts();
        }
        timer = window.setTimeout(poll, 4000);
      } catch {
        if (active) timer = window.setTimeout(poll, 4000);
      }
    };
    void poll();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [status?.running]);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const result = await api.ssoCheckStatus();
        if (!active) return;
        setSsoCheckRunning(!!result.sso_check.running);
        if (result.sso_check.running) timer = window.setTimeout(poll, 2500);
      } catch {
        if (active) timer = window.setTimeout(poll, 5000);
      }
    };
    void poll();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    setResultPage(1);
  }, [status?.run_id]);

  useEffect(() => {
    if (status?.running) setActiveTab("logs");
  }, [status?.running, status?.run_id]);

  useEffect(() => {
    if (!resultsOpen) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setResultsOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [resultsOpen]);

  const candidates = accounts;
  const eligibleCandidates = candidates.filter((item) => !!item.email && !!item.password);
  const selectedIds = Object.entries(selected).filter(([, value]) => value).map(([id]) => Number(id));
  const allSelected = eligibleCandidates.length > 0 && eligibleCandidates.every((item) => selected[item.id]);
  const botRiskByAccountId = useMemo(() => {
    const map = new Map<number, boolean>();
    for (const item of accounts) {
      map.set(item.id, !!item.bot_risk);
    }
    return map;
  }, [accounts]);

  const start = async () => {
    if (!selectedIds.length || status?.running) return;
    if (!window.confirm(`重新登录选中的 ${selectedIds.length} 个账号，刷新 SSO 并重建授权文件？`)) return;
    setStarting(true);
    try {
      const result = await api.startBatchRelogin(selectedIds);
      recordedRun.current = "";
      seenRunIdRef.current = result.relogin.run_id || "";
      logViewVersionRef.current += 1;
      afterLogIdRef.current = 0;
      setLogs([]);
      setResultsOpen(false);
      setActiveTab("logs");
      setStopping(false);
      setStatus(result.relogin);
      notify("重新登录任务已启动", "success");
    } catch (error: any) {
      notify(error.message || "启动失败", "error");
    } finally {
      setStarting(false);
    }
  };

  const stop = async () => {
    if (!status?.running || stopping) return;
    setStopping(true);
    try {
      const result = await api.stopRelogin();
      setStatus(result.relogin);
      setActiveTab("logs");
      notify("已请求停止重新登录", "success");
    } catch (error: any) {
      notify(error.message || "停止失败", "error");
    } finally {
      setStopping(false);
    }
  };

  const selectAllMatchingAccounts = async () => {
    setSelectingAll(true);
    try {
      const result = await api.actionableAccountIds("relogin", query.trim(), riskFilter);
      const ids = result.ids || [];
      setSelected(Object.fromEntries(ids.map((id) => [id, true])));
      notify(`已选择 ${ids.length} 个可重新登录账号`, "success");
    } catch (error: any) {
      notify(error.message || "选择全部账号失败", "error");
    } finally {
      setSelectingAll(false);
    }
  };

  const progress = status?.total_count
    ? Math.min(100, Math.round((status.completed_count / status.total_count) * 100))
    : 0;
  const visibleResults = status?.items || [];
  const safeResultPage = Math.min(resultPage, Math.max(1, Math.ceil(visibleResults.length / RELOGIN_RESULT_PAGE_SIZE)));
  const pagedResults = visibleResults.slice((safeResultPage - 1) * RELOGIN_RESULT_PAGE_SIZE, safeResultPage * RELOGIN_RESULT_PAGE_SIZE);

  return (
    <div className="space-y-5">
      <AccountPageContext crumbs={[{ label: "重新登录" }]} />
      <PageHeader
        title="重新登录"
        description="集中选择已有账号，按当前低流量设置刷新 SSO 后直接重建 CPA 与 Grok2API 授权文件。页面提示 Wrong email address or password 时记为账号密码错误，不再当成 SSO 超时。"
        actions={<>
          <Button variant="outline" disabled={!visibleResults.length} onClick={() => setResultsOpen(true)}>
            <ListChecks className="h-4 w-4" aria-hidden="true" />
            本次结果{visibleResults.length ? ` (${status?.completed_count || 0}/${status?.total_count || visibleResults.length})` : ""}
          </Button>
          <Link
            to="/accounts/relogin/history"
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            <History className="h-4 w-4" aria-hidden="true" />
            登录历史
          </Link>
        </>}
      />

      {status?.running ? (
        <Card className="overflow-hidden border-sky-200">
          <div className="flex flex-col gap-4 p-4 sm:p-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="flex items-center gap-2 font-semibold text-slate-950">
                  <Loader2 className="h-4 w-4 animate-spin text-sky-600" aria-hidden="true" />
                  {status.stopping ? "正在停止重新登录" : "正在重新登录"}
                </div>
                <p className="mt-1 text-xs text-slate-500">{status.stage} · {status.email || "准备账号"}</p>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="default">{status.completed_count}/{status.total_count}</Badge>
                <Button variant="destructive" size="sm" onClick={() => void stop()} disabled={stopping || !!status.stopping}>
                  {stopping || status.stopping ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Square className="h-4 w-4" aria-hidden="true" />}
                  停止任务
                </Button>
              </div>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-sky-500 transition-[width]" style={{ width: `${progress}%` }} />
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              {[
                ["已完成", status.completed_count],
                ["成功", status.success_count],
                ["失败", status.failed_count],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded-lg bg-slate-50 px-3 py-2">
                  <div className="text-lg font-semibold tabular-nums text-slate-950">{value}</div>
                  <div className="text-[11px] text-slate-500">{label}</div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      ) : null}

      {status?.run_id && status.finished_at && !status.running ? (
        <Card className="p-4 sm:p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="font-semibold text-slate-950">最近一次重新登录已完成</div>
              <div className="mt-1 text-sm text-slate-500">成功 {status.success_count} · 失败 {status.failed_count}</div>
            </div>
            <Link
              to={`/accounts/relogin/history/${status.run_id}`}
              className="inline-flex min-h-10 items-center justify-center rounded-lg bg-slate-900 px-4 text-sm font-medium text-white"
            >
              查看报告
            </Link>
          </div>
        </Card>
      ) : null}

      <div className="grid grid-cols-2 gap-1 rounded-xl bg-slate-100/80 p-1" role="tablist" aria-label="重新登录页面分类">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "accounts"}
          onClick={() => setActiveTab("accounts")}
          className={`flex items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-sm font-medium transition ${activeTab === "accounts" ? "bg-white text-sky-700 shadow-sm ring-1 ring-sky-100" : "text-slate-500 hover:bg-white/70 hover:text-slate-700"}`}
        >
          <Users className="h-4 w-4" aria-hidden="true" />
          账号
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "logs"}
          onClick={() => setActiveTab("logs")}
          className={`flex items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-sm font-medium transition ${activeTab === "logs" ? "bg-white text-sky-700 shadow-sm ring-1 ring-sky-100" : "text-slate-500 hover:bg-white/70 hover:text-slate-700"}`}
        >
          <TerminalSquare className="h-4 w-4" aria-hidden="true" />
          日志
          {status?.running ? <Badge variant="default">运行中</Badge> : logs.length ? <Badge variant="secondary">{logs.length}</Badge> : null}
        </button>
      </div>

      <div className={activeTab === "logs" ? "" : "hidden"} role="tabpanel" aria-label="重新登录日志">
        <LiveLogBoard
          logs={logs}
          running={!!status?.running}
          lastError={status?.error}
          title="重新登录日志"
          description="按时间顺序显示浏览器登录、Turnstile 和授权重建日志。"
          ariaLabel="实时重新登录日志"
          emptyIdleHint="等待日志…选择账号并启动重新登录后会在这里实时输出。"
          emptyRunningHint="重新登录进行中，正在等待实时日志…"
          statusRunningLabel="日志持续同步中"
          statusIdleLabel={status?.run_id ? "最近一次任务日志" : "等待新任务"}
          extraMeta={status?.total_count ? `完成 ${status.completed_count}/${status.total_count}` : undefined}
          onClearView={() => {
            const latestId = Math.max(afterLogIdRef.current, Number(status?.latest_log_id || 0));
            logViewVersionRef.current += 1;
            afterLogIdRef.current = latestId;
            setLogs([]);
          }}
          onToast={notify}
        />
      </div>

      <div className={activeTab === "accounts" ? "" : "hidden"} role="tabpanel" aria-label="重新登录账号">
      <Card className="overflow-hidden">
        <AccountFilterBar>
            <div className="w-full sm:w-48">
              <label htmlFor="relogin-risk-filter" className="mb-1.5 block text-xs font-medium text-slate-500">风控状态</label>
              <Select id="relogin-risk-filter" value={riskFilter} onChange={(event) => { setRiskFilter(event.target.value); setSelected({}); }} aria-label="按账号风控状态筛选">
                <option value="">全部账号</option>
                <option value="0">正常账号</option>
                <option value="1">异常账号</option>
                <option value="unknown">未检查 / 未知</option>
              </Select>
            </div>
              <div className="w-full sm:w-80">
                <label htmlFor="relogin-search" className="mb-1.5 block text-xs font-medium text-slate-500">搜索账号</label>
                <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
                <Input id="relogin-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索邮箱或服务商" className="pl-9" />
                </div>
            </div>
        </AccountFilterBar>
        <AccountSelectionToolbar
          allVisibleSelected={allSelected}
          selectableCount={eligibleCandidates.length}
          selectedCount={selectedIds.length}
          total={total}
          loading={loading}
          selectingAll={selectingAll}
          onTogglePage={(checked) => setSelected((previous) => { const next = { ...previous }; for (const item of eligibleCandidates) checked ? (next[item.id] = true) : delete next[item.id]; return next; })}
          onSelectAll={() => void selectAllMatchingAccounts()}
          onClear={() => setSelected({})}
          actions={<Button size="sm" onClick={() => void start()} disabled={!selectedIds.length || starting || !!status?.running || ssoCheckRunning}>{starting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCcw className="h-4 w-4" aria-hidden="true" />}重新登录</Button>}
        />
        {ssoCheckRunning ? <p className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700 sm:px-5">SSO 风控检查正在运行，完成后可启动重新登录。</p> : null}

        {loading ? (
          <div className="flex min-h-52 items-center justify-center text-sm text-slate-500">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />加载账号
          </div>
        ) : candidates.length ? (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[1080px] text-left text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="w-12 px-4 py-3"><span className="sr-only">选择账号</span></th>
                    <th className="px-4 py-3 font-medium">账号</th>
                    <th className="px-4 py-3 font-medium">邮箱来源</th>
                    <th className="w-[160px] px-4 py-3 font-medium">创建时间</th>
                    <th className="px-4 py-3 font-medium">登录凭据</th>
                    <th className="px-4 py-3 font-medium">SSO 风控</th>
                    <th className="px-4 py-3 font-medium">授权文件</th>
                    <th className="px-4 py-3 font-medium">最近结果</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {candidates.map((item) => (
                    <tr key={item.id} className="hover:bg-slate-50/70">
                      <td className="px-4 py-3"><input type="checkbox" disabled={!item.email || !item.password} checked={!!selected[item.id]} onChange={(event) => setSelected((old) => ({ ...old, [item.id]: event.target.checked }))} /></td>
                      <td className="px-4 py-3">
                        <AccountEmailLabel
                          email={item.email}
                          botRisk={!!item.bot_risk}
                          emailClassName="text-sm text-slate-900"
                        />
                      </td>
                      <td className="px-4 py-3"><EmailProviderLabel provider={item.provider} /></td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">{item.finished_at || item.started_at || "未记录"}</td>
                      <td className="px-4 py-3"><Badge variant={item.email && item.password ? "success" : "warning"}>{item.email && item.password ? "有效" : "缺失"}</Badge></td>
                      {(() => { const risk = accountRiskStatus(item); return <td className="px-4 py-3"><Badge variant={risk.variant}>{risk.label}</Badge></td>; })()}
                      <td className="px-4 py-3"><div className="flex flex-wrap gap-1.5"><Badge variant={item.cpa_auth_available ? "success" : "secondary"}>CPA {item.cpa_auth_available ? "有效" : "缺失"}</Badge><Badge variant={item.grok2api_auth_available ? "success" : "secondary"}>G2A {item.grok2api_auth_available ? "有效" : "缺失"}</Badge></div></td>
                      {(() => { const outcome = reloginOutcome(item); return <td className="px-4 py-3"><Badge variant={outcome.variant}>{outcome.label}</Badge></td>; })()}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="divide-y divide-slate-100 md:hidden">
              {candidates.map((item) => (
                <label key={item.id} className={`flex items-start gap-3 p-4 ${!item.email || !item.password ? "opacity-60" : ""}`}>
                  <input type="checkbox" className="mt-1" disabled={!item.email || !item.password} checked={!!selected[item.id]} onChange={(event) => setSelected((old) => ({ ...old, [item.id]: event.target.checked }))} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-2">
                      <AccountEmailLabel
                        email={item.email}
                        botRisk={!!item.bot_risk}
                        className="min-w-0 flex-1"
                        emailClassName="text-sm text-slate-900"
                      />
                      <EmailProviderIcon provider={item.provider} />
                    </div>
                    <div className="mt-1 text-xs text-slate-500">创建于 {item.finished_at || item.started_at || "未记录"}</div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs"><div className="rounded-lg bg-slate-50 px-3 py-2"><div className="text-slate-400">登录凭据</div><div className="mt-1"><Badge variant={item.email && item.password ? "success" : "warning"}>{item.email && item.password ? "有效" : "缺失"}</Badge></div></div><div className="rounded-lg bg-slate-50 px-3 py-2"><div className="text-slate-400">SSO 风控</div><div className="mt-1"><Badge variant={accountRiskStatus(item).variant}>{accountRiskStatus(item).label}</Badge></div></div></div>
                    <div className="flex flex-wrap gap-1.5"><Badge variant={item.cpa_auth_available ? "success" : "secondary"}>CPA {item.cpa_auth_available ? "有效" : "缺失"}</Badge><Badge variant={item.grok2api_auth_available ? "success" : "secondary"}>G2A {item.grok2api_auth_available ? "有效" : "缺失"}</Badge><Badge variant={reloginOutcome(item).variant}>{reloginOutcome(item).label}</Badge></div>
                  </div>
                </label>
              ))}
            </div>
          </>
        ) : (
          <div className="p-4"><EmptyState title="没有可重新登录的账号" description="账号需要同时保存有效邮箱和密码。" /></div>
        )}
        {total > 0 ? (
          <PaginationBar
            page={page}
            pageSize={pageSize}
            total={total}
            loading={loading}
            onPageChange={(nextPage) => void loadAccounts(nextPage)}
            onPageSizeChange={(nextSize) => {
              setPageSize(nextSize);
              setSelected({});
              void loadAccounts(1, query, nextSize);
            }}
          />
        ) : null}
      </Card>
      </div>

      {resultsOpen && status && visibleResults.length ? <ReloginResultsDrawer status={status} items={pagedResults} page={safeResultPage} botRiskByAccountId={botRiskByAccountId} onPageChange={setResultPage} onClose={() => setResultsOpen(false)} /> : null}
      <Toast message={toast.message} tone={toast.tone} />
    </div>
  );
}
