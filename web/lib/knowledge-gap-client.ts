export type KnowledgeGapSeverity = "high" | "medium" | "low";

export type KnowledgeGap = {
  id: string;
  knowledgePointId: string;
  concept: string;
  chapterId: string;
  category: string;
  severity: KnowledgeGapSeverity;
  score: number;
  evidence: string;
  evidenceItems: Array<Record<string, unknown>>;
  recommendedActions: string[];
  status: string;
  source: string;
  updatedAt: string;
};

export type KnowledgeGapSummary = {
  openCount: number;
  highCount: number;
  mediumCount: number;
  lowCount: number;
  resolvedCount: number;
};

export type KnowledgeGapState = {
  userId: string;
  knowledgeGaps: KnowledgeGap[];
  summary: KnowledgeGapSummary;
  files: Record<string, string>;
};

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function numberValue(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function parseArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string" || !value.trim()) return [];
  try {
    return parseArray(JSON.parse(value));
  } catch {
    return [];
  }
}

function normalizeScore(value: unknown): number {
  const score = numberValue(value);
  return Math.max(0, Math.min(100, score > 0 && score <= 1 ? score * 100 : score));
}

export function normalizeKnowledgeGapItems(value: unknown): KnowledgeGap[] {
  return parseArray(value)
    .map((raw, index) => {
      const item = recordValue(raw);
      const rawSeverity = stringValue(item.severity, "medium").toLowerCase();
      const severity: KnowledgeGapSeverity =
        rawSeverity === "high" || rawSeverity === "low" ? rawSeverity : "medium";
      return {
        id: stringValue(item.gap_id ?? item.id, `gap-${index + 1}`),
        knowledgePointId: stringValue(item.knowledge_point_id ?? item.knowledgePointId),
        concept: stringValue(item.concept, "未命名知识漏洞"),
        chapterId: stringValue(item.chapter_id ?? item.chapterId, "未归类"),
        category: stringValue(item.category, "未归类"),
        severity,
        score: normalizeScore(item.score),
        evidence: stringValue(item.evidence, "暂无可展示的证据摘要。"),
        evidenceItems: parseArray(item.evidence_items ?? item.evidence_items_json)
          .map(recordValue)
          .filter((entry) => Object.keys(entry).length > 0),
        recommendedActions: parseArray(
          item.recommended_actions ?? item.recommended_actions_json,
        )
          .map((entry) => String(entry).trim())
          .filter(Boolean),
        status: stringValue(item.status, "open").toLowerCase(),
        source: stringValue(item.source, "system"),
        updatedAt: stringValue(item.updated_at ?? item.updatedAt),
      };
    })
    .filter((gap) => gap.status !== "resolved" && gap.status !== "closed");
}

export function normalizeKnowledgeGapPayload(value: unknown): KnowledgeGapState {
  const payload = recordValue(value);
  const summary = recordValue(payload.knowledge_gap_summary ?? payload.summary);
  const gaps = normalizeKnowledgeGapItems(payload.knowledge_gaps);
  const countBySeverity = (severity: KnowledgeGapSeverity) =>
    gaps.filter((gap) => gap.severity === severity).length;
  const files = recordValue(payload.knowledge_gap_files ?? payload.files);
  const highCount = countBySeverity("high");
  const mediumCount = countBySeverity("medium");
  const lowCount = countBySeverity("low");
  return {
    userId: stringValue(payload.user_id),
    knowledgeGaps: gaps,
    summary: {
      // The backend summary includes historical resolved rows.  The cards above
      // render only active gaps, so derive their counts from the same filtered
      // collection to keep the headline and severity totals consistent.
      openCount: gaps.length,
      highCount,
      mediumCount,
      lowCount,
      resolvedCount: numberValue(summary.resolved_count),
    },
    files: Object.fromEntries(
      Object.entries(files).map(([key, entry]) => [key, String(entry ?? "")]),
    ),
  };
}

export async function loadBackendKnowledgeGaps(userId: string): Promise<KnowledgeGapState> {
  const response = await fetch(
    `/api/storage/users/${encodeURIComponent(userId)}/knowledge-gaps`,
    { cache: "no-store" },
  );
  const data = (await response.json()) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(
      stringValue(data.error) || `知识漏洞接口返回 HTTP ${response.status}`,
    );
  }
  return normalizeKnowledgeGapPayload(data);
}
