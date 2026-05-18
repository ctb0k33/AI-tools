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
  const generated = summarizePostText(item.text || "");
  if (generated) return generated;
  return item.raw?.summary || item.text || item.title || "No summary available.";
}

export function getDisplayTitle(item: DigestItem): string {
  const titles = extractRoundupTitles(item.text || "");
  if (titles.length >= 3) return `Weekly Roundup: ${titles.length} ethresear.ch research posts`;
  return item.title || "Untitled";
}

export function getScore(item: DigestItem): number {
  return Number(item.raw?.personalized_score ?? item.score ?? item.raw?.technical_score ?? 0);
}

export function getTechnicalScore(item: DigestItem): number {
  return Number(item.raw?.technical_score ?? item.score ?? 0);
}

export function getPersonalizationAdjustment(item: DigestItem): number {
  return Number(item.raw?.personalization_adjustment ?? 0);
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
    ...(item.raw?.personalization_reasons || []),
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

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function truncateAtWord(value: string, limit: number): string {
  const cleaned = normalizeText(value);
  if (cleaned.length <= limit) return cleaned;
  const candidate = cleaned.slice(0, limit).trim();
  const lastSpace = candidate.lastIndexOf(" ");
  return (lastSpace > 80 ? candidate.slice(0, lastSpace) : candidate).trim();
}

function extractRoundupTitles(text: string): string[] {
  const cleaned = normalizeText(text);
  if (!cleaned) return [];
  const linkCount = (cleaned.match(/ethresear\.ch\/t\/\d+/gi) || []).length;
  if (!/weekly roundup/i.test(cleaned) && linkCount < 3) return [];
  const normalized = cleaned
    .replace(/https?:\/\/\s*ethresear\.ch\/t\/\d+/gi, " <ETHRESEARCH_LINK> ")
    .replace(/\b\d+\s+comment\(s\)\s+this\s+week\b/gi, " <ROUNDUP_BREAK> ")
    .replace(/\b\d+\s+comments?\s+this\s+week\b/gi, " <ROUNDUP_BREAK> ");
  const seen = new Set<string>();
  const titles: string[] = [];
  for (const piece of normalized.split(/<ETHRESEARCH_LINK>|<ROUNDUP_BREAK>/g)) {
    const candidate = normalizeText(piece)
      .replace(/^weekly roundup\s*/i, "")
      .replace(/^(new post on\s+)?https?:\/\/\s*/i, "")
      .replace(/^[\s\-:;]+|[\s\-:;]+$/g, "");
    const key = candidate.toLowerCase();
    if (candidate.length < 12 || key === "weekly roundup" || key === "ethresearchbot" || seen.has(key)) continue;
    seen.add(key);
    titles.push(candidate);
  }
  return titles;
}

function summarizePostText(text: string): string {
  const titles = extractRoundupTitles(text);
  if (titles.length < 3) return "";
  const selected: string[] = [];
  for (const title of titles) {
    const candidate = `Weekly roundup covering ${titles.length} ethresear.ch posts: ${[...selected, title].join("; ")}`;
    if (candidate.length > 700 && selected.length) break;
    selected.push(title);
    if (selected.length >= 8) break;
  }
  const suffix = selected.length === titles.length ? "" : `; and ${titles.length - selected.length} more`;
  return truncateAtWord(`Weekly roundup covering ${titles.length} ethresear.ch posts: ${selected.join("; ")}${suffix}`, 700);
}
