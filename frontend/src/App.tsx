import {
  AlertTriangle,
  BarChart3,
  Bookmark,
  CalendarDays,
  EyeOff,
  ExternalLink,
  FileJson,
  Filter,
  Link2,
  Loader2,
  Play,
  RefreshCw,
  Search,
  ThumbsDown,
  ThumbsUp,
  Upload,
  Users,
} from "lucide-react";
import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import type { DigestApiResponse, DigestItem, DigestPayload, FeedbackAction, Filters } from "./types";
import {
  formatDateTime,
  getDisplayTitle,
  getHost,
  getPersonalizationAdjustment,
  getPrimaryCategory,
  getScore,
  getSummary,
  getTags,
  getTechnicalScore,
  groupBySection,
  matchesText,
  uniqueSorted,
} from "./utils";

const SAMPLE_PATH = "/sample/daily_research_digest.json";
const ROLE_STORAGE_KEY = "dailyResearchRole";
const DEFAULT_ROLE = "researcher";
const FALLBACK_ROLES: RoleOption[] = [
  { id: "researcher", label: "Researcher", description: "Technical protocol and DeFi research" },
  { id: "bd", label: "BD", description: "Partnerships, integrations, and adoption" },
  { id: "marketing", label: "Marketing", description: "Narratives, campaigns, and market attention" },
  { id: "operations", label: "Operations", description: "Incidents, upgrades, and operational alerts" },
];

type RoleOption = {
  id: string;
  label: string;
  description?: string;
};

const DEFAULT_FILTERS: Filters = {
  query: "",
  source: "All",
  section: "All",
  category: "All",
  author: "All",
  minScore: 0,
};

function App() {
  const [digest, setDigest] = useState<DigestPayload | null>(null);
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [loadError, setLoadError] = useState("");
  const [apiStatus, setApiStatus] = useState<{ kind: "idle" | "running" | "success" | "error"; message: string }>({
    kind: "idle",
    message: "",
  });
  const [feedbackByKey, setFeedbackByKey] = useState<Record<string, FeedbackAction>>({});
  const [feedbackToast, setFeedbackToast] = useState<{ kind: "success" | "error"; message: string } | null>(null);
  const [isCollecting, setIsCollecting] = useState(false);
  const [collectionDate, setCollectionDate] = useState(() => todayForInput());
  const [roleOptions, setRoleOptions] = useState<RoleOption[]>(FALLBACK_ROLES);
  const [selectedRole, setSelectedRole] = useState(() => localStorage.getItem(ROLE_STORAGE_KEY) || DEFAULT_ROLE);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const toastTimerRef = useRef<number | null>(null);

  useEffect(() => {
    loadRoleOptions();
  }, []);

  useEffect(() => {
    localStorage.setItem(ROLE_STORAGE_KEY, selectedRole);
    setFeedbackByKey({});
    loadInitialDigest(selectedRole);
  }, [selectedRole]);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    };
  }, []);

  function showFeedbackToast(kind: "success" | "error", message: string) {
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    setFeedbackToast({ kind, message });
    toastTimerRef.current = window.setTimeout(() => {
      setFeedbackToast(null);
      toastTimerRef.current = null;
    }, 3200);
  }

  async function loadRoleOptions() {
    try {
      const payload = await requestApi("/api/roles");
      if (Array.isArray(payload.roles) && payload.roles.length) {
        setRoleOptions(payload.roles);
      }
    } catch {
      setRoleOptions(FALLBACK_ROLES);
    }
  }

  async function loadInitialDigest(roleId = selectedRole) {
    setLoadError("");
    setApiStatus({ kind: "running", message: "Loading latest generated output..." });
    try {
      const today = todayForInput();
      const payload = await requestApi(`/api/latest?role=${encodeURIComponent(roleId)}&date=${encodeURIComponent(today)}`);
      if (!payload.digest) throw new Error("API response did not include a digest.");
      setDigest(payload.digest);
      setFilters(DEFAULT_FILTERS);
      setApiStatus({
        kind: "success",
        message: `Loaded ${payload.paths?.json || "latest digest output"}.`,
      });
      return;
    } catch {
      try {
        const payload = await requestApi(`/api/latest?role=${encodeURIComponent(roleId)}`);
        if (!payload.digest) throw new Error("API response did not include a digest.");
        setDigest(payload.digest);
        setFilters(DEFAULT_FILTERS);
        setApiStatus({
          kind: "success",
          message: `Loaded latest available output: ${payload.paths?.json || "daily_research_digest.json"}.`,
        });
        return;
      } catch {
        await loadSample("API output was not available, so the bundled sample was loaded.");
      }
    }
  }

  async function loadSample(statusMessage = "") {
    setLoadError("");
    setApiStatus({ kind: statusMessage ? "success" : "idle", message: statusMessage });
    try {
      const response = await fetch(SAMPLE_PATH, { cache: "no-store" });
      if (!response.ok) throw new Error(`Sample data returned ${response.status}`);
      const payload = (await response.json()) as DigestPayload;
      setDigest(payload);
      setFilters(DEFAULT_FILTERS);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not load sample data.");
    }
  }

  async function loadLatestOutput() {
    setLoadError("");
    setApiStatus({ kind: "running", message: `Loading latest output for ${collectionDate}...` });
    try {
      const payload = await requestApi(
        `/api/latest?role=${encodeURIComponent(selectedRole)}&date=${encodeURIComponent(collectionDate)}`,
      );
      if (!payload.digest) throw new Error("API response did not include a digest.");
      setDigest(payload.digest);
      setFilters(DEFAULT_FILTERS);
      setApiStatus({
        kind: "success",
        message: `Loaded ${payload.paths?.json || "latest digest output"}.`,
      });
    } catch (error) {
      setApiStatus({
        kind: "error",
        message: formatApiError(error),
      });
    }
  }

  async function collectDailyData() {
    setLoadError("");
    setIsCollecting(true);
    setApiStatus({ kind: "running", message: `Collecting daily data for ${collectionDate}. A browser window may open while X is scanned.` });
    try {
      const payload = await requestApi("/api/collect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          date: collectionDate,
          timezone: "Asia/Saigon",
          role: selectedRole,
          profileDir: "profiles/ctb0k33",
          xBackend: "playwright",
        }),
      });
      if (!payload.digest) throw new Error("Collection finished, but no digest was returned.");
      setDigest(payload.digest);
      setFilters(DEFAULT_FILTERS);
      setApiStatus({
        kind: "success",
        message: `Collection complete. Loaded ${payload.paths?.json || "new digest output"}.`,
      });
    } catch (error) {
      setApiStatus({
        kind: "error",
        message: formatApiError(error),
      });
    } finally {
      setIsCollecting(false);
    }
  }

  async function handleFileUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setLoadError("");
    setApiStatus({ kind: "idle", message: "" });
    try {
      const payload = JSON.parse(await file.text()) as DigestPayload;
      if (!Array.isArray(payload.items)) throw new Error("JSON does not include an items array.");
      setDigest(payload);
      setFilters(DEFAULT_FILTERS);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not parse JSON file.");
    } finally {
      event.target.value = "";
    }
  }

  async function submitFeedback(item: DigestItem, action: FeedbackAction) {
    const key = feedbackKey(item);
    const previous = feedbackByKey[key];
    const isClearing = previous === action;
    setFeedbackByKey((current) => {
      const next = { ...current };
      if (isClearing) delete next[key];
      else next[key] = action;
      return next;
    });
    try {
      await requestApi("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: isClearing ? "clear" : action,
          item,
          role: selectedRole,
          reason: isClearing ? `dashboard_toggle_clear:${action}` : "",
        }),
      });
      showFeedbackToast(
        "success",
        isClearing
          ? `${feedbackLabel(action)} feedback cleared.`
          : `Feedback saved: ${feedbackLabel(action)}. It will influence future ranking.`,
      );
    } catch (error) {
      setFeedbackByKey((current) => {
        const next = { ...current };
        if (previous) next[key] = previous;
        else delete next[key];
        return next;
      });
      showFeedbackToast("error", formatApiError(error));
    }
  }

  const items = digest?.items || [];
  const sources = useMemo(() => ["All", ...uniqueSorted(items.map((item) => item.source))], [items]);
  const sections = useMemo(() => ["All", ...uniqueSorted(items.map((item) => item.section))], [items]);
  const authors = useMemo(() => ["All", ...uniqueSorted(items.map((item) => item.author))], [items]);
  const categories = useMemo(
    () => ["All", ...uniqueSorted(items.flatMap((item) => getTags(item)))],
    [items],
  );

  const filteredItems = useMemo(() => {
    return items
      .filter((item) => filters.source === "All" || item.source === filters.source)
      .filter((item) => filters.section === "All" || item.section === filters.section)
      .filter((item) => filters.author === "All" || item.author === filters.author)
      .filter((item) => filters.category === "All" || getTags(item).includes(filters.category))
      .filter((item) => getScore(item) >= filters.minScore)
      .filter((item) => matchesText(item, filters.query))
      .sort((a, b) => {
        const scoreDelta = getScore(b) - getScore(a);
        if (scoreDelta !== 0) return scoreDelta;
        return new Date(b.published_at || 0).getTime() - new Date(a.published_at || 0).getTime();
      });
  }, [filters, items]);

  const groupedItems = useMemo(() => groupBySection(filteredItems), [filteredItems]);
  const topAuthors = useMemo(() => getTopAuthors(filteredItems), [filteredItems]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">Daily research</div>
          <h1>DeFi / Core News Dashboard</h1>
        </div>
        <div className="header-actions">
          <label className="role-control">
            <span>Role</span>
            <div>
              <Users size={16} />
              <select value={selectedRole} onChange={(event) => setSelectedRole(event.target.value)}>
                {roleOptions.map((role) => (
                  <option value={role.id} key={role.id}>
                    {role.label}
                  </option>
                ))}
              </select>
            </div>
          </label>
          <label className="date-control">
            <span>Run date</span>
            <input type="date" value={collectionDate} onChange={(event) => setCollectionDate(event.target.value)} />
          </label>
          <button className="primary-button" type="button" onClick={collectDailyData} disabled={isCollecting}>
            {isCollecting ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
            Collect Daily Data
          </button>
          <button className="icon-button" type="button" onClick={loadLatestOutput} title="Load latest generated output" disabled={isCollecting}>
            <RefreshCw size={18} />
          </button>
          <button className="primary-button" type="button" onClick={() => fileInputRef.current?.click()}>
            <Upload size={18} />
            Upload JSON
          </button>
          <input ref={fileInputRef} className="hidden-input" type="file" accept=".json" onChange={handleFileUpload} />
        </div>
      </header>

      {apiStatus.message ? (
        <div className={`status-banner status-${apiStatus.kind}`}>
          {apiStatus.kind === "running" ? <Loader2 className="spin" size={18} /> : apiStatus.kind === "error" ? <AlertTriangle size={18} /> : <FileJson size={18} />}
          <span>{apiStatus.message}</span>
        </div>
      ) : null}

      {digest ? <DigestMeta digest={digest} visibleCount={filteredItems.length} /> : null}

      {loadError ? (
        <div className="alert">
          <AlertTriangle size={18} />
          <span>{loadError}</span>
        </div>
      ) : null}

      {feedbackToast ? (
        <div className={`feedback-toast feedback-toast-${feedbackToast.kind}`} role="status" aria-live="polite">
          {feedbackToast.kind === "error" ? <AlertTriangle size={18} /> : <FileJson size={18} />}
          <span>{feedbackToast.message}</span>
        </div>
      ) : null}

      <section className="layout-grid">
        <aside className="filters-panel">
          <div className="panel-title">
            <Filter size={17} />
            Filters
          </div>
          <label className="field">
            <span>Search</span>
            <div className="search-box">
              <Search size={16} />
              <input
                value={filters.query}
                onChange={(event) => setFilters({ ...filters, query: event.target.value })}
                placeholder="author, protocol, exploit..."
              />
            </div>
          </label>
          <SelectField label="Source" value={filters.source} values={sources} onChange={(source) => setFilters({ ...filters, source })} />
          <SelectField label="Section" value={filters.section} values={sections} onChange={(section) => setFilters({ ...filters, section })} />
          <SelectField label="Category" value={filters.category} values={categories} onChange={(category) => setFilters({ ...filters, category })} />
          <SelectField label="Author" value={filters.author} values={authors} onChange={(author) => setFilters({ ...filters, author })} />
          <label className="field">
            <span>Min score</span>
            <input
              type="range"
              min="0"
              max="12"
              value={filters.minScore}
              onChange={(event) => setFilters({ ...filters, minScore: Number(event.target.value) })}
            />
            <strong>{filters.minScore}</strong>
          </label>
          <button className="secondary-button" type="button" onClick={() => setFilters(DEFAULT_FILTERS)}>
            Reset filters
          </button>

          <div className="side-block">
            <div className="side-block-title">Top authors</div>
            {topAuthors.length ? (
              topAuthors.map(([author, count]) => (
                <button
                  key={author}
                  className="author-row"
                  type="button"
                  onClick={() => setFilters({ ...filters, author })}
                >
                  <span>{author}</span>
                  <strong>{count}</strong>
                </button>
              ))
            ) : (
              <p className="muted">No matching authors.</p>
            )}
          </div>
        </aside>

        <section className="feed">
          {digest?.warnings?.length ? <Warnings warnings={digest.warnings} /> : null}
          {groupedItems.length ? (
            groupedItems.map(([section, sectionItems]) => (
              <section className="feed-section" key={section}>
                <div className="section-heading">
                  <h2>{section}</h2>
                  <span>{sectionItems.length}</span>
                </div>
                <div className="news-list">
                  {sectionItems.map((item) => (
                    <NewsCard
                      key={`${item.url}-${item.title}`}
                      item={item}
                      selectedFeedback={feedbackByKey[feedbackKey(item)]}
                      onFeedback={submitFeedback}
                    />
                  ))}
                </div>
              </section>
            ))
          ) : (
            <div className="empty-state">
              <FileJson size={26} />
              <h2>No matching items</h2>
              <p>Adjust filters or upload another digest JSON.</p>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}

function DigestMeta({ digest, visibleCount }: { digest: DigestPayload; visibleCount: number }) {
  const includedDates = digest.date_filter?.included_dates?.join(", ") || digest.date;
  const sourceCount = Object.entries(digest.stats.source_counts || {})
    .map(([source, count]) => `${source}: ${count}`)
    .join(" | ");
  const categoryCount = Object.entries(digest.stats.category_counts || {})
    .slice(0, 5)
    .map(([category, count]) => `${category}: ${count}`)
    .join(" | ");

  return (
    <section className="stats-strip">
      <Metric icon={<CalendarDays size={18} />} label="Window" value={includedDates} />
      <Metric icon={<BarChart3 size={18} />} label="Visible / total" value={`${visibleCount} / ${digest.stats.total_items}`} />
      <Metric icon={<Link2 size={18} />} label="Sources" value={sourceCount || "None"} />
      <Metric icon={<Filter size={18} />} label="Categories" value={categoryCount || "None"} />
    </section>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="metric">
      <div className="metric-icon">{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function SelectField({
  label,
  value,
  values,
  onChange,
}: {
  label: string;
  value: string;
  values: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {values.map((option) => (
          <option value={option} key={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function Warnings({ warnings }: { warnings: string[] }) {
  return (
    <details className="warnings">
      <summary>
        <AlertTriangle size={18} />
        Collection warnings ({warnings.length})
      </summary>
      <ul>
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
    </details>
  );
}

function NewsCard({
  item,
  selectedFeedback,
  onFeedback,
}: {
  item: DigestItem;
  selectedFeedback?: FeedbackAction;
  onFeedback: (item: DigestItem, action: FeedbackAction) => void;
}) {
  const score = getScore(item);
  const technicalScore = getTechnicalScore(item);
  const personalizationAdjustment = getPersonalizationAdjustment(item);
  const tags = getTags(item);
  const category = getPrimaryCategory(item);
  const reasons = item.raw?.technical_reasons || [];
  const personalizationReasons = item.raw?.personalization_reasons || [];
  const host = getHost(item.url);

  return (
    <article className="news-card">
      <div className="card-topline">
        <span className={`category-pill category-${slug(category)}`}>{category}</span>
        <span>{item.source}</span>
        <span>{formatDateTime(item.published_at)}</span>
        {score ? <strong>Score {score}</strong> : null}
        {personalizationAdjustment ? (
          <span className={personalizationAdjustment > 0 ? "score-boost" : "score-penalty"}>
            Personal {personalizationAdjustment > 0 ? "+" : ""}
            {personalizationAdjustment}
          </span>
        ) : null}
      </div>
      <h3>{getDisplayTitle(item)}</h3>
      <p>{getSummary(item)}</p>
      <div className="meta-row">
        {item.author ? <button className="text-chip">{item.author}</button> : null}
        {item.raw?.source_profile ? <button className="text-chip">profile: @{item.raw.source_profile}</button> : null}
        {host ? <button className="text-chip">{host}</button> : null}
      </div>
      <div className="tag-row">
        {tags.map((tag) => (
          <span key={tag}>{tag}</span>
        ))}
        {reasons.slice(0, 5).map((reason) => (
          <span className="reason" key={reason}>
            {reason}
          </span>
        ))}
        {personalizationReasons.slice(0, 3).map((reason) => (
          <span className="personal-reason" key={reason}>
            {reason}
          </span>
        ))}
      </div>
      {personalizationAdjustment ? (
        <div className="score-note">
          Base technical score {technicalScore}; personalized ranking adjusted this item by {personalizationAdjustment > 0 ? "+" : ""}
          {personalizationAdjustment}.
        </div>
      ) : null}
      <div className="feedback-row" aria-label="Feedback controls">
        <FeedbackButton
          action="interested"
          active={selectedFeedback === "interested"}
          icon={<ThumbsUp size={14} />}
          label="Interested"
          onClick={() => onFeedback(item, "interested")}
        />
        <FeedbackButton
          action="save"
          active={selectedFeedback === "save"}
          icon={<Bookmark size={14} />}
          label="Save"
          onClick={() => onFeedback(item, "save")}
        />
        <FeedbackButton
          action="not_relevant"
          active={selectedFeedback === "not_relevant"}
          icon={<ThumbsDown size={14} />}
          label="Not relevant"
          onClick={() => onFeedback(item, "not_relevant")}
        />
        <FeedbackButton
          action="hide_author"
          active={selectedFeedback === "hide_author"}
          icon={<EyeOff size={14} />}
          label="Hide author"
          onClick={() => onFeedback(item, "hide_author")}
        />
      </div>
      {item.text ? (
        <details className="post-body">
          <summary>Original post</summary>
          <p>{item.text}</p>
        </details>
      ) : null}
      {item.url ? (
        <a className="open-link" href={item.url} target="_blank" rel="noreferrer">
          Open source
          <ExternalLink size={16} />
        </a>
      ) : null}
    </article>
  );
}

function FeedbackButton({
  action,
  active,
  icon,
  label,
  onClick,
}: {
  action: FeedbackAction;
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button className={`feedback-button feedback-${action} ${active ? "active" : ""}`} type="button" onClick={onClick}>
      {icon}
      {label}
    </button>
  );
}

function getTopAuthors(items: DigestItem[]): Array<[string, number]> {
  const counts = new Map<string, number>();
  for (const item of items) {
    if (!item.author) continue;
    counts.set(item.author, (counts.get(item.author) || 0) + 1);
  }
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 8);
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "other";
}

function feedbackKey(item: DigestItem): string {
  return item.url || `${item.author || ""}::${item.title}`;
}

function feedbackLabel(action: FeedbackAction): string {
  const labels: Record<FeedbackAction, string> = {
    interested: "Interested",
    save: "Saved",
    not_relevant: "Not relevant",
    hide_author: "Hide author",
  };
  return labels[action];
}

async function requestApi(path: string, init?: RequestInit): Promise<DigestApiResponse> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    throw new Error(`${error instanceof Error ? error.message : "Could not reach local API."} Start it with: python -m tools.daily_research.dashboard_api`);
  }

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? ((await response.json()) as DigestApiResponse)
    : ({ error: await response.text() } as DigestApiResponse);

  if (!response.ok || payload.error) {
    throw new Error(payload.error || `API returned ${response.status}`);
  }
  return payload;
}

function formatApiError(error: unknown): string {
  const message = error instanceof Error ? error.message : "Unknown API error.";
  if (message.includes("Failed to fetch") || message.includes("NetworkError")) {
    return "Local API is not running. Start it with: python -m tools.daily_research.dashboard_api";
  }
  return message;
}

function todayForInput(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Saigon",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

export default App;
