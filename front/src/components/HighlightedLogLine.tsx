import { memo } from "react";
import { cn } from "@/lib/utils";
import { logHaystack, splitHighlightedText } from "@/lib/logSearch";

export const HighlightedLogLine = memo(function HighlightedLogLine({
  item,
  query,
  activeOccurrence,
  toneClassName,
}: {
  item: { id: number; time: string; message: string };
  query: string;
  activeOccurrence: number;
  toneClassName?: string;
}) {
  const searching = Boolean(query.trim());
  const fullText = logHaystack(item);
  const parts = searching ? splitHighlightedText(fullText, query, activeOccurrence) : [];

  return (
    <div
      data-log-id={item.id}
      className={cn(
        "border-b border-slate-200/60 py-0.5 last:border-0 [contain-intrinsic-size:auto_24px]",
        searching ? "" : "[content-visibility:auto]",
        activeOccurrence >= 0 ? "rounded-sm bg-amber-50" : ""
      )}
    >
      {searching ? (
        <span className={cn("whitespace-pre-wrap break-all", toneClassName)}>
          {parts.map((part, index) =>
            part.highlight ? (
              <mark
                key={`${part.occurrence}-${index}`}
                data-log-match={`${item.id}-${part.occurrence}`}
                className={cn(
                  "rounded-sm px-0.5",
                  part.active ? "bg-orange-400 text-slate-950" : "bg-amber-200 text-slate-900"
                )}
              >
                {part.text}
              </mark>
            ) : (
              <span key={`plain-${index}`}>{part.text}</span>
            )
          )}
        </span>
      ) : (
        <>
          <span className="text-sky-600">[{item.time}]</span>{" "}
          <span className={cn("whitespace-pre-wrap break-all", toneClassName)}>{item.message}</span>
        </>
      )}
    </div>
  );
});
