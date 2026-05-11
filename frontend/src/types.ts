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
    source_profile?: string;
    links?: string[];
    [key: string]: unknown;
  };
};

export type DigestPayload = {
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
  paths?: {
    json?: string;
    markdown?: string;
    outputDir?: string;
  };
  command?: string;
  stdout?: string;
  error?: string;
};
