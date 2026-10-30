import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownToLine, Copy, RotateCcw, TerminalSquare } from "lucide-react";
import type { LogItem } from "@/lib/api";
import { HighlightedLogLine } from "@/components/HighlightedLogLine";
import { LogSearchField } from "@/components/LogSearchField";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Switch } from "@/components/ui";
import { clampMatchIndex, collectLogMatches } from "@/lib/logSearch";
import { cn, copyText } from "@/lib/utils";

type LogTone = "default" | "success" | "error" | "warn" | "info";
type DisplayLogItem = LogItem & { tone: LogTone };

const DEFAULT_RENDERED_LOGS = 300;
const LOG_RENDER_STEP = 300;

function detectLogTone(message: string): LogTone {
  if (/(error|failed|failure|exception|traceback|拒绝|失败|异常|拦截|timeout|timed out)/i.test(message)) {
    if (/(success|成功|完成)/i.test(message) && !/(fail|失败|error)/i.test(message)) return "success";
    return "error";
  }
  if (/(warn|warning|风险|注意|重试|retry)/i.test(message)) return "warn";
  if (/(success|成功|完成|imported|saved|已保存)/i.test(message)) return "success";
  if (/(stage|step|开始|启动|waiting|proxy|browser|Turnstile|SSO)/i.test(message)) return "info";
  return "default";
}

const logToneClass: Record<LogTone, string> = {
  default: "text-slate-700",
  success: "text-emerald-700",
  error: "text-rose-700",
  warn: "text-amber-700",
  info: "text-slate-800",
};

export function LiveLogBoard({
  logs,
  running,
  lastError,
  title = "实时日志",
  description = "按时间顺序显示浏览器和流程日志。",
  ariaLabel = "实时日志",
  emptyIdleHint = "等待日志…启动任务后会在这里实时输出。",
  emptyRunningHint = "任务运行中，正在等待实时日志…",
  statusRunningLabel = "日志持续同步中",
  statusIdleLabel = "等待新任务",
  extraMeta,
  onClearView,
  onToast,
}: {
  logs: LogItem[];
  running: boolean;
  lastError?: string;
  title?: string;
  description?: string;
  ariaLabel?: string;
  emptyIdleHint?: string;
  emptyRunningHint?: string;
  statusRunningLabel?: string;
  statusIdleLabel?: string;
  extraMeta?: string;
  onClearView?: () => void;
  onToast?: (message: string, tone?: "default" | "success" | "error") => void;
}) {
  const [renderedLogLimit, setRenderedLogLimit] = useState(DEFAULT_RENDERED_LOGS);
  const [autoScroll, setAutoScroll] = useState(true);
  const [showJumpBottom, setShowJumpBottom] = useState(false);
  const [logQuery, setLogQuery] = useState("");
  const [logLevel, setLogLevel] = useState<"all" | LogTone>("all");
  const [activeMatchIndex, setActiveMatchIndex] = useState(0);
  const logRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const userPinnedRef = useRef(false);
  const lastFocusedMatchRef = useRef("");
  const query = logQuery.trim();
  const searching = Boolean(query);

  const displayLogs = useMemo<DisplayLogItem[]>(
    () =>
      logs.map((item) => ({
        ...item,
        tone: detectLogTone(item.message),
      })),
    [logs]
  );

  const levelLogs = useMemo(() => {
    if (logLevel === "all") return displayLogs;
    return displayLogs.filter((item) => item.tone === logLevel);
  }, [displayLogs, logLevel]);

  const matches = useMemo(() => collectLogMatches(levelLogs, query), [levelLogs, query]);
  const safeMatchIndex = clampMatchIndex(activeMatchIndex, matches.length);
  const currentMatch = matches[safeMatchIndex] || null;

  const renderedLogs = useMemo(
    () => levelLogs.slice(-renderedLogLimit),
    [levelLogs, renderedLogLimit]
  );
  const hiddenLogCount = Math.max(levelLogs.length - renderedLogs.length, 0);
  const latestRenderedLogId = renderedLogs[renderedLogs.length - 1]?.id || 0;

  useEffect(() => {
    setRenderedLogLimit(DEFAULT_RENDERED_LOGS);
  }, [logLevel]);

  useEffect(() => {
    setActiveMatchIndex(matches.length ? matches.length - 1 : 0);
    lastFocusedMatchRef.current = "";
  }, [query, logLevel]);

  useEffect(() => {
    setActiveMatchIndex((current) => clampMatchIndex(current, matches.length));
  }, [matches.length]);

  useEffect(() => {
    if (autoScroll && !userPinnedRef.current && !searching && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
      setShowJumpBottom(false);
    }
  }, [latestRenderedLogId, autoScroll, searching]);

  useEffect(() => {
    if (!currentMatch) return;
    const needed = levelLogs.length - currentMatch.lineIndex;
    if (needed > renderedLogLimit) {
      setRenderedLogLimit(needed);
      return;
    }
    const focusKey = `${currentMatch.logId}:${currentMatch.occurrence}`;
    if (lastFocusedMatchRef.current === focusKey) return;
    userPinnedRef.current = true;
    setShowJumpBottom(true);
    window.requestAnimationFrame(() => {
      const root = logRef.current;
      if (!root) return;
      lastFocusedMatchRef.current = focusKey;
      const mark = root.querySelector(`[data-log-match="${currentMatch.logId}-${currentMatch.occurrence}"]`);
      const line = root.querySelector(`[data-log-id="${currentMatch.logId}"]`);
      (mark || line)?.scrollIntoView({ block: "center", inline: "nearest" });
    });
  }, [currentMatch?.logId, currentMatch?.occurrence, currentMatch?.lineIndex, renderedLogLimit, levelLogs.length]);

  const onLogScroll = () => {
    const el = logRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
    userPinnedRef.current = !nearBottom;
    setShowJumpBottom(!nearBottom);
  };

  const jumpToBottom = () => {
    const el = logRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    userPinnedRef.current = false;
    setShowJumpBottom(false);
  };

  const revealOlderLogs = () => {
    const el = logRef.current;
    const previousHeight = el?.scrollHeight || 0;
    const previousTop = el?.scrollTop || 0;
    setRenderedLogLimit((current) => Math.min(levelLogs.length, current + LOG_RENDER_STEP));
    window.requestAnimationFrame(() => {
      if (!el) return;
      el.scrollTop = previousTop + Math.max(el.scrollHeight - previousHeight, 0);
    });
  };

  const copyVisibleLogs = async () => {
    const text = levelLogs.map((item) => `[${item.time}] ${item.message}`).join("\n");
    if (!text) {
      onToast?.("没有可复制的日志", "error");
      return;
    }
    const ok = await copyText(text);
    onToast?.(ok ? `已复制 ${levelLogs.length} 行日志` : "复制失败", ok ? "success" : "error");
  };

  const goToMatch = (index: number) => {
    if (!matches.length) return;
    const next = (index + matches.length) % matches.length;
    lastFocusedMatchRef.current = "";
    setActiveMatchIndex(next);
  };

  const levelFilters: Array<{ id: "all" | LogTone; label: string }> = [
    { id: "all", label: "全部" },
    { id: "error", label: "错误" },
    { id: "warn", label: "警告" },
    { id: "success", label: "成功" },
    { id: "info", label: "流程" },
  ];

  return (
    <Card className="min-w-0 overflow-hidden">
      <CardHeader className="space-y-3 border-b border-slate-100">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <TerminalSquare className="h-4 w-4 text-slate-600" />
              {title}
            </CardTitle>
            <CardDescription>{lastError ? `最近错误：${lastError}` : description}</CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => void copyVisibleLogs()}>
              <Copy className="h-3.5 w-3.5" />
              复制
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                onClearView?.();
                onToast?.(running ? "视图已清空，将继续接收新日志" : "日志视图已清空");
              }}
              disabled={!onClearView}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              清空视图
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
          <LogSearchField
            query={logQuery}
            matchCount={matches.length}
            activeIndex={safeMatchIndex}
            onQueryChange={setLogQuery}
            onPrev={() => goToMatch(safeMatchIndex - 1)}
            onNext={() => goToMatch(safeMatchIndex + 1)}
            inputRef={searchInputRef}
          />
          <div className="flex flex-wrap items-center gap-1.5">
            {levelFilters.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setLogLevel(item.id)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-xs font-medium transition",
                  logLevel === item.id ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
          <label className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600">
            <Switch
              checked={autoScroll}
              onCheckedChange={(checked) => {
                setAutoScroll(checked);
                if (checked) {
                  userPinnedRef.current = false;
                  requestAnimationFrame(jumpToBottom);
                }
              }}
              label="自动滚动"
            />
            <span>自动滚动</span>
          </label>
        </div>
      </CardHeader>

      <CardContent className="relative p-3 sm:p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
          <span className="flex items-center gap-2">
            <span className={cn("h-2 w-2 rounded-full", running ? "animate-pulse bg-amber-500" : "bg-emerald-500")} />
            {running ? statusRunningLabel : statusIdleLabel}
          </span>
          <span className="tabular-nums">
            {extraMeta ? `${extraMeta} · ` : ""}
            显示 {renderedLogs.length} / {levelLogs.length} · 缓冲 {logs.length}
            {searching ? ` · 匹配 ${matches.length ? `${safeMatchIndex + 1}/${matches.length}` : 0}` : ""}
          </span>
        </div>

        <div className="sr-only" aria-live="polite" aria-atomic="true">
          {searching
            ? matches.length
              ? `第 ${safeMatchIndex + 1} / ${matches.length} 个匹配`
              : "没有匹配的日志"
            : renderedLogs.length
              ? `最新日志：${renderedLogs[renderedLogs.length - 1].message}`
              : ""}
        </div>

        <div
          ref={logRef}
          onScroll={onLogScroll}
          role="log"
          aria-label={ariaLabel}
          aria-live="off"
          className="font-mono-log h-[50dvh] min-h-[360px] max-h-[640px] overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-6 sm:h-[540px] sm:p-4"
        >
          {levelLogs.length === 0 ? (
            <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 text-center text-slate-500">
              <div>{logs.length === 0 ? (running ? emptyRunningHint : emptyIdleHint) : "没有符合筛选条件的日志。"}</div>
            </div>
          ) : (
            <>
              {hiddenLogCount > 0 ? (
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 font-sans text-xs text-slate-500">
                  <span>为保持流畅，前面 {hiddenLogCount} 行暂未生成页面节点。</span>
                  <button
                    type="button"
                    onClick={revealOlderLogs}
                    className="font-medium text-sky-600 hover:text-sky-700"
                  >
                    再显示 {Math.min(LOG_RENDER_STEP, hiddenLogCount)} 行
                  </button>
                </div>
              ) : null}
              {renderedLogs.map((item) => (
                <HighlightedLogLine
                  key={item.id}
                  item={item}
                  query={query}
                  activeOccurrence={currentMatch?.logId === item.id ? currentMatch.occurrence : -1}
                  toneClassName={logToneClass[item.tone]}
                />
              ))}
            </>
          )}
        </div>

        {showJumpBottom ? (
          <button
            type="button"
            onClick={jumpToBottom}
            className="absolute bottom-8 right-8 inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-md hover:bg-slate-50"
          >
            <ArrowDownToLine className="h-3.5 w-3.5" />
            回到底部
          </button>
        ) : null}
      </CardContent>
    </Card>
  );
}
