export type LogSearchItem = {
  id: number;
  time?: string;
  message: string;
};

export type LogSearchMatch = {
  logId: number;
  occurrence: number;
  lineIndex: number;
};

export type HighlightPart = {
  text: string;
  highlight: boolean;
  active: boolean;
  occurrence: number;
};

export function logHaystack(item: LogSearchItem): string {
  return `[${item.time || ""}] ${item.message}`;
}

export function collectLogMatches(items: LogSearchItem[], query: string): LogSearchMatch[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const matches: LogSearchMatch[] = [];
  items.forEach((item, lineIndex) => {
    const haystack = logHaystack(item).toLowerCase();
    let from = 0;
    let occurrence = 0;
    while (from < haystack.length) {
      const index = haystack.indexOf(needle, from);
      if (index < 0) break;
      matches.push({ logId: item.id, occurrence, lineIndex });
      occurrence += 1;
      from = index + needle.length;
    }
  });
  return matches;
}

export function splitHighlightedText(text: string, query: string, activeOccurrence: number): HighlightPart[] {
  const needle = query.trim();
  if (!needle) return [{ text, highlight: false, active: false, occurrence: -1 }];
  const lower = text.toLowerCase();
  const target = needle.toLowerCase();
  const parts: HighlightPart[] = [];
  let from = 0;
  let occurrence = 0;
  while (from < text.length) {
    const index = lower.indexOf(target, from);
    if (index < 0) {
      parts.push({ text: text.slice(from), highlight: false, active: false, occurrence: -1 });
      break;
    }
    if (index > from) {
      parts.push({ text: text.slice(from, index), highlight: false, active: false, occurrence: -1 });
    }
    parts.push({
      text: text.slice(index, index + needle.length),
      highlight: true,
      active: occurrence === activeOccurrence,
      occurrence,
    });
    occurrence += 1;
    from = index + needle.length;
  }
  return parts;
}

export function clampMatchIndex(index: number, total: number): number {
  if (total <= 0) return 0;
  if (index < 0) return 0;
  if (index >= total) return total - 1;
  return index;
}
