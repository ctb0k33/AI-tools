export type DigestItem = {
  source: string;
  section: string;
  title: string;
  url: string;
  category?: string;
  author?: string;
  published_at?: string;
  text?: string;
  tags?: string[];
  score?: number;
  raw?: {
    summary?: string;
    technical_score?: number;
    technical_reasons?: string[];
    personalized_score?: number;
    personalization_adjustment?: number;
    personalization_reasons?: string[];
    source_profile?: string;
    links?: string[];
    [key: string]: unknown;
  };
};

export type DigestPayload = {
  role?: {
    id?: string;
    label?: string;
    description?: string;
  };
  date: string;
  timezone: string;
  generated_at: string;
  date_filter?: {
    lookback_days?: number;
    included_dates?: string[];
  };
  stats: {
    total_items: number;
    source_counts: Record<string, number>;
    category_counts: Record<string, number>;
  };
  warnings: string[];
  items: DigestItem[];
};

export type Filters = {
  query: string;
  source: string;
  section: string;
  category: string;
  author: string;
  minScore: number;
};

export type DigestApiResponse = {
  digest?: DigestPayload;
  roles?: Array<{
    id: string;
    label: string;
    description?: string;
  }>;
  paths?: {
    json?: string;
    markdown?: string;
    outputDir?: string;
  };
  command?: string;
  stdout?: string;
  error?: string;
  ok?: boolean;
  feedback?: {
    path?: string;
    record?: FeedbackRecord;
    model?: PreferenceModel;
    events?: FeedbackRecord[];
  };
};

export type FeedbackAction = "interested" | "save" | "not_relevant" | "hide_author";

export type FeedbackRecord = {
  key: string;
  action: string;
  reason?: string;
  created_at: string;
  url?: string;
  title?: string;
  author?: string;
  source?: string;
  section?: string;
  tags?: string[];
  technical_reasons?: string[];
  signals?: string[];
};

export type PreferenceModel = {
  author_weights?: Record<string, number>;
  signal_weights?: Record<string, number>;
  hidden_authors?: string[];
  url_feedback?: Record<string, string>;
  feedback_count?: number;
};
