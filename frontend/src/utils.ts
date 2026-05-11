import type { DigestItem } from "./types";

export function formatDateTime(value?: string): string {
  if (!value) return "Unknown time";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

export function getSummary(item: DigestItem): string {
  return item.raw?.summary || item.text || item.title || "No summary available.";
}

export function getScore(item: DigestItem): number {
  return Number(item.raw?.technical_score ?? item.score ?? 0);
}

export function getTags(item: DigestItem): string[] {
  const tags = item.tags?.length ? item.tags : item.category ? [item.category] : ["Other"];
  return Array.from(new Set(tags.filter(Boolean)));
}

export function getPrimaryCategory(item: DigestItem): string {
  return getTags(item)[0] || "Other";
}

export function getHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export function uniqueSorted(values: Array<string | undefined>): string[] {
  return Array.from(new Set(values.filter(Boolean) as string[])).sort((a, b) => a.localeCompare(b));
}

export function matchesText(item: DigestItem, query: string): boolean {
  if (!query.trim()) return true;
  const haystack = [
    item.title,
    item.author,
    item.section,
    item.source,
    item.text,
    item.raw?.summary,
    ...(item.tags || []),
    ...(item.raw?.technical_reasons || []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((token) => haystack.includes(token));
}

export function groupBySection(items: DigestItem[]): Array<[string, DigestItem[]]> {
  const groups = new Map<string, DigestItem[]>();
  for (const item of items) {
    const key = item.section || "Other";
    groups.set(key, [...(groups.get(key) || []), item]);
  }
  return Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0]));
}
