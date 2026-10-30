import type { Ref } from "react";
import { ChevronDown, ChevronUp, Search } from "lucide-react";
import { Button, Input } from "@/components/ui";

export function LogSearchField({
  query,
  matchCount,
  activeIndex,
  onQueryChange,
  onPrev,
  onNext,
  inputRef,
}: {
  query: string;
  matchCount: number;
  activeIndex: number;
  onQueryChange: (value: string) => void;
  onPrev: () => void;
  onNext: () => void;
  inputRef?: Ref<HTMLInputElement>;
}) {
  const searching = Boolean(query.trim());
  return (
    <div className="relative min-w-0 flex-1">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
      <Input
        ref={inputRef}
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === "F3" || event.key === "ArrowDown") {
            event.preventDefault();
            event.shiftKey ? onPrev() : onNext();
            return;
          }
          if (event.key === "ArrowUp") {
            event.preventDefault();
            onPrev();
            return;
          }
          if (event.key === "Escape" && query) {
            event.preventDefault();
            onQueryChange("");
          }
        }}
        placeholder="查找日志关键字…"
        className="h-9 pl-9 pr-[7.5rem]"
        aria-label="查找日志"
      />
      <div className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-0.5">
        <span className="min-w-10 px-1 text-right text-[11px] tabular-nums text-slate-500">
          {searching ? (matchCount ? `${activeIndex + 1}/${matchCount}` : "无结果") : ""}
        </span>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="h-7 w-7 min-h-7"
          onMouseDown={(event) => event.preventDefault()}
          onClick={onPrev}
          disabled={!matchCount}
          aria-label="上一个匹配"
          title="上一个匹配"
        >
          <ChevronUp className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="h-7 w-7 min-h-7"
          onMouseDown={(event) => event.preventDefault()}
          onClick={onNext}
          disabled={!matchCount}
          aria-label="下一个匹配"
          title="下一个匹配"
        >
          <ChevronDown className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}
