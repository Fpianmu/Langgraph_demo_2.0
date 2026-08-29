export type ResourceDifficultyRecord = {
  record_id: string;
  user_id?: string;
  resource_id: string;
  resource_type: string;
  chapter_id: string;
  profile_score: number;
  resource_difficulty: number;
  difficulty_delta: number;
  alignment_score: number;
  source_node?: string;
  resource_meta?: Record<string, unknown>;
  created_at?: string;
};

export type ResourceDifficultyTrace = {
  user_id: string;
  capability_profile_score?: {
    overall?: number;
    dimensions?: Record<string, number>;
  };
  resource_difficulty_records: ResourceDifficultyRecord[];
  record_count: number;
};

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function numberValue(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function parseResourceMeta(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value === "string" && value.trim()) {
    try {
      return recordValue(JSON.parse(value));
    } catch {
      return {};
    }
  }
  return {};
}

export function normalizeResourceDifficultyTrace(value: unknown): ResourceDifficultyTrace {
  const payload = recordValue(value);
  const profile = recordValue(payload.capability_profile_score);
  const records = Array.isArray(payload.resource_difficulty_records)
    ? payload.resource_difficulty_records
    : [];
  return {
    user_id: String(payload.user_id ?? ""),
    capability_profile_score: {
      overall: numberValue(profile.overall),
      dimensions: recordValue(profile.dimensions) as Record<string, number>,
    },
    resource_difficulty_records: records.map((raw, index) => {
      const record = recordValue(raw);
      return {
        record_id: String(record.record_id ?? `difficulty-${index + 1}`),
        user_id: String(record.user_id ?? payload.user_id ?? ""),
        resource_id: String(record.resource_id ?? ""),
        resource_type: String(record.resource_type ?? "resource"),
        chapter_id: String(record.chapter_id ?? ""),
        profile_score: numberValue(record.profile_score),
        resource_difficulty: numberValue(record.resource_difficulty),
        difficulty_delta: numberValue(record.difficulty_delta),
        alignment_score: numberValue(record.alignment_score),
        source_node: String(record.source_node ?? ""),
        resource_meta: parseResourceMeta(record.resource_meta ?? record.resource_meta_json),
        created_at: String(record.created_at ?? ""),
      };
    }),
    record_count: numberValue(payload.record_count) || records.length,
  };
}

export async function loadResourceDifficultyTrace(
  userId: string,
): Promise<ResourceDifficultyTrace> {
  const response = await fetch(
    `/api/storage/users/${encodeURIComponent(userId)}/difficulty-trace`,
    { cache: "no-store" },
  );
  const data = (await response.json()) as ResourceDifficultyTrace & {
    error?: string;
  };
  if (!response.ok) {
    throw new Error(data.error || `资源匹配接口返回 HTTP ${response.status}`);
  }
  return normalizeResourceDifficultyTrace(data);
}
