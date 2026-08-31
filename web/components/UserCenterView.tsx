"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import type { LearnerProfile } from "@/lib/agent-contract";
import {
  capabilityResultList,
  type CapabilityAssessment,
} from "@/lib/capability-assessment";
import type { LearningProgressResult } from "@/lib/learning-progress";
import {
  loadResourceDifficultyTrace,
  type ResourceDifficultyRecord,
} from "@/lib/resource-difficulty-client";
import type {
  KnowledgeGap,
  KnowledgeGapSummary,
} from "@/lib/knowledge-gap-client";
import ProfileMarkdownEditor from "@/components/ProfileMarkdownEditor";

type MemoryEvent = {
  id: string;
  title: string;
  detail: string;
  time: string;
};

type UserCenterViewProps = {
  userId: string;
  profile: LearnerProfile;
  assessment: CapabilityAssessment;
  capabilityOverall: number;
  progress: LearningProgressResult;
  setProfile: Dispatch<SetStateAction<LearnerProfile>>;
  knowledgeGaps: KnowledgeGap[];
  knowledgeGapSummary: KnowledgeGapSummary | null;
  events: MemoryEvent[];
  busy: boolean;
  onReload: () => void | Promise<void>;
  onSaved: (profile: LearnerProfile) => void | Promise<void>;
};

const CHAPTER_NAMES: Record<string, string> = {
  "1": "数控车床基础认知",
  "2": "上机安全基础",
  "3": "数控车床基本操作",
  "4": "CNC 代码练习与仿真",
  "5": "上机测试与结果审查",
};

const SECTION_NAMES: Record<string, string> = {
  "1.1": "数控车床基础认知",
  "1.2": "数控机床组成、工作原理与特点",
  "1.3": "数控机床分类与数控车床类型",
  "2.1": "数控车床安全规范",
  "3.1": "数控系统上电关机与手动操作",
  "3.2": "刀架移动及安全操作",
  "3.3": "对刀及加工设置",
  "3.4": "坐标系设置与输入方式",
  "3.5": "刀补设置与试切对刀",
  "3.6": "程序编辑与管理",
  "3.7": "自动运行与运行控制",
  "3.8": "异常处理与手动运行复盘",
  "4.1": "代码线上练习与仿真",
  "5.1": "上机操作与结果审查",
};

const CATEGORY_NAMES: Record<string, string> = {
  safety: "安全规范",
  foundations: "专业基础",
  process_planning: "工艺规划",
  programming: "数控编程",
  machining_operation: "操作加工",
  quality_control: "质量检测",
  maintenance: "维护诊断",
  advanced_manufacturing: "先进制造",
};

const RESOURCE_TYPE_NAMES: Record<string, string> = {
  lecture: "学习讲义",
  practice: "实训练习",
  quiz: "Quiz 测验",
};

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value.trim() : fallback;
}

function chapterKey(chapterId: string): string {
  return chapterId.match(/^\d+/)?.[0] || "other";
}

function chapterTitle(chapterId: string): string {
  const key = chapterKey(chapterId);
  return key === "other"
    ? "其他知识点"
    : `Chapter ${key} · ${CHAPTER_NAMES[key] || "未命名章节"}`;
}

function severityLabel(severity: KnowledgeGap["severity"]): string {
  if (severity === "high") return "高优先级";
  if (severity === "medium") return "中优先级";
  return "低优先级";
}

function resourceTitle(record: ResourceDifficultyRecord): string {
  const metaTitle = stringValue(record.resource_meta?.title);
  if (metaTitle) return metaTitle;
  const section = SECTION_NAMES[record.chapter_id];
  const type = RESOURCE_TYPE_NAMES[record.resource_type] || record.resource_type;
  return section ? `${record.chapter_id} ${section}` : `${type} · ${record.resource_id}`;
}

function matchingVerdict(delta: number): {
  label: string;
  tone: "matched" | "hard" | "easy";
  advice: string;
} {
  if (Math.abs(delta) <= 10) {
    return { label: "匹配", tone: "matched", advice: "难度与当前水平接近，可按计划学习。" };
  }
  if (delta > 20) {
    return { label: "明显偏难", tone: "hard", advice: "建议先补齐前置知识，再进入该资源。" };
  }
  if (delta > 10) {
    return { label: "略难", tone: "hard", advice: "可以学习，建议配合讲义和分步提示。" };
  }
  return { label: "偏简单", tone: "easy", advice: "可用于快速复习，随后提升学习难度。" };
}

function shortDate(value: string): string {
  if (!value) return "时间未记录";
  const date = new Date(value.includes("T") ? value : `${value.replace(" ", "T")}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function UserCenterRadar({
  items,
  centerValue,
}: {
  items: Array<{ label: string; value: number }>;
  centerValue: number;
}) {
  const center = 150;
  const radius = 92;
  const point = (index: number, value: number) => {
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / Math.max(items.length, 1);
    const scaled = radius * Math.max(0, Math.min(100, value)) / 100;
    return [center + Math.cos(angle) * scaled, center + Math.sin(angle) * scaled];
  };
  const ring = (ratio: number) =>
    items
      .map((_, index) => point(index, ratio * 100).join(","))
      .join(" ");
  const data = items.map((item, index) => point(index, item.value).join(",")).join(" ");

  return (
    <div className="user-center-radar">
      <svg viewBox="0 0 300 300" role="img" aria-label="八维岗位能力评估图">
        {[0.25, 0.5, 0.75, 1].map((ratio) => (
          <polygon className="user-center-radar-ring" points={ring(ratio)} key={ratio} />
        ))}
        {items.map((_, index) => {
          const [x, y] = point(index, 100);
          return <line className="user-center-radar-axis" x1={center} y1={center} x2={x} y2={y} key={index} />;
        })}
        <polygon className="user-center-radar-shape" points={data} />
        {items.map((item, index) => {
          const [x, y] = point(index, item.value);
          const [labelX, labelY] = point(index, 126);
          return (
            <g key={item.label}>
              <circle className="user-center-radar-point" cx={x} cy={y} r="3.5" />
              <text className="user-center-radar-label" x={labelX} y={labelY}>
                <tspan x={labelX}>{item.label}</tspan>
                <tspan x={labelX} dy="11">{Math.round(item.value)}</tspan>
              </text>
            </g>
          );
        })}
        <circle className="user-center-radar-center" cx={center} cy={center} r="36" />
        <text className="user-center-radar-value" x={center} y={center - 2}>{Math.round(centerValue)}</text>
        <text className="user-center-radar-caption" x={center} y={center + 14}>综合暂估</text>
      </svg>
    </div>
  );
}

function ResourceMatchChart({ records }: { records: ResourceDifficultyRecord[] }) {
  const [hoveredId, setHoveredId] = useState(records[0]?.record_id || "");
  const width = 820;
  const height = 300;
  const left = 52;
  const right = 28;
  const top = 25;
  const bottom = 64;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const xFor = (index: number) =>
    records.length <= 1
      ? left + plotWidth / 2
      : left + (plotWidth * index) / (records.length - 1);
  const yFor = (value: number) => top + ((100 - value) / 100) * plotHeight;
  const resourcePoints = records
    .map((record, index) => `${xFor(index)},${yFor(record.resource_difficulty)}`)
    .join(" ");
  const profilePoints = records
    .map((record, index) => `${xFor(index)},${yFor(record.profile_score)}`)
    .join(" ");
  const hoveredIndex = Math.max(
    0,
    records.findIndex((record) => record.record_id === hoveredId),
  );
  const hovered = records[hoveredIndex];

  return (
    <div className="resource-match-chart">
      <div className="resource-chart-legend">
        <span><i className="resource-line difficulty" />资源难度</span>
        <span><i className="resource-line learner" />用户水平</span>
      </div>
      <div className="resource-chart-canvas">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="资源难度与用户水平匹配曲线">
          {[0, 25, 50, 75, 100].map((score) => {
            const y = yFor(score);
            return (
              <g key={score}>
                <line className="resource-chart-grid" x1={left} y1={y} x2={width - right} y2={y} />
                <text className="resource-chart-y-label" x={left - 12} y={y + 4}>{score}</text>
              </g>
            );
          })}
          {records.length > 1 && (
            <>
              <polyline className="resource-chart-path difficulty" points={resourcePoints} />
              <polyline className="resource-chart-path learner" points={profilePoints} />
            </>
          )}
          {records.map((record, index) => {
            const x = xFor(index);
            const active = record.record_id === hoveredId;
            return (
              <g
                className={active ? "active" : ""}
                key={record.record_id}
                tabIndex={0}
                onMouseEnter={() => setHoveredId(record.record_id)}
                onFocus={() => setHoveredId(record.record_id)}
              >
                <line className="resource-chart-connector" x1={x} y1={yFor(record.resource_difficulty)} x2={x} y2={yFor(record.profile_score)} />
                <circle className="resource-chart-dot difficulty" cx={x} cy={yFor(record.resource_difficulty)} r={active ? 6 : 4.5} />
                <circle className="resource-chart-dot learner" cx={x} cy={yFor(record.profile_score)} r={active ? 6 : 4.5} />
                <text className="resource-chart-x-label" x={x} y={height - 35}>
                  <tspan x={x}>{record.chapter_id || `资源 ${index + 1}`}</tspan>
                  <tspan x={x} dy="13">{RESOURCE_TYPE_NAMES[record.resource_type] || record.resource_type}</tspan>
                </text>
                <title>{`${resourceTitle(record)}：资源难度 ${Math.round(record.resource_difficulty)}，用户水平 ${Math.round(record.profile_score)}，差值 ${record.difficulty_delta > 0 ? "+" : ""}${Math.round(record.difficulty_delta)}`}</title>
              </g>
            );
          })}
        </svg>
        {hovered && (
          <div
            className="resource-chart-tooltip"
            style={{ left: `${(xFor(hoveredIndex) / width) * 100}%` }}
          >
            <strong>{resourceTitle(hovered)}</strong>
            <span>资源难度 {Math.round(hovered.resource_difficulty)} · 用户水平 {Math.round(hovered.profile_score)}</span>
            <span>差值 {hovered.difficulty_delta > 0 ? "+" : ""}{Math.round(hovered.difficulty_delta)} · {matchingVerdict(hovered.difficulty_delta).label}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export function UserCenterView({
  userId,
  profile,
  assessment,
  capabilityOverall,
  progress,
  knowledgeGaps,
  knowledgeGapSummary,
  busy,
  onReload,
}: UserCenterViewProps) {
  const [openSections, setOpenSections] = useState({
    overview: true,
    gaps: true,
    matching: true,
    custom: true,
  });
  const [selectedGap, setSelectedGap] = useState<KnowledgeGap | null>(null);
  const [expandedChapter, setExpandedChapter] = useState("");
  const [resourceRecords, setResourceRecords] = useState<ResourceDifficultyRecord[]>([]);
  const [resourceProfileScore, setResourceProfileScore] = useState<number | null>(null);
  const [resourceBusy, setResourceBusy] = useState(false);
  const [resourceError, setResourceError] = useState("");
  const [selectedResourceChapter, setSelectedResourceChapter] = useState("");

  const capabilityResults = capabilityResultList(assessment, profile.level);
  const radarItems = capabilityResults.map((result) => ({
    label: result.shortLabel,
    value: result.score ?? 0,
  }));
  const gaps = knowledgeGaps;
  const gapsByChapter = useMemo(() => {
    const groups = new Map<string, KnowledgeGap[]>();
    gaps.forEach((gap) => {
      const key = chapterKey(gap.chapterId);
      groups.set(key, [...(groups.get(key) || []), gap]);
    });
    return [...groups.entries()].sort(([left], [right]) => left.localeCompare(right));
  }, [gaps]);

  const resourceChapters = useMemo(() => {
    return [...new Set(resourceRecords.map((record) => chapterKey(record.chapter_id)))].sort();
  }, [resourceRecords]);
  const visibleResourceRecords = useMemo(() => {
    const seen = new Set<string>();
    return resourceRecords.filter((record) => {
      if (selectedResourceChapter && chapterKey(record.chapter_id) !== selectedResourceChapter) return false;
      const key = `${record.resource_id}|${record.chapter_id}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).sort((left, right) => {
      const leftTime = Date.parse(left.created_at || "") || 0;
      const rightTime = Date.parse(right.created_at || "") || 0;
      return leftTime - rightTime;
    });
  }, [resourceRecords, selectedResourceChapter]);
  const overallAlignment = visibleResourceRecords.length
    ? Math.round(
        visibleResourceRecords.reduce((sum, record) => sum + record.alignment_score, 0) /
          visibleResourceRecords.length,
      )
    : null;
  const loadResources = useCallback(async () => {
    setResourceBusy(true);
    setResourceError("");
    try {
      const trace = await loadResourceDifficultyTrace(userId);
      setResourceRecords(trace.resource_difficulty_records);
      setResourceProfileScore(trace.capability_profile_score?.overall ?? null);
      setSelectedResourceChapter((current) =>
        current && trace.resource_difficulty_records.some(
          (record) => chapterKey(record.chapter_id) === current,
        )
          ? current
          : "",
      );
    } catch (error) {
      setResourceError(error instanceof Error ? error.message : "资源匹配记录读取失败");
    } finally {
      setResourceBusy(false);
    }
  }, [userId]);

  useEffect(() => {
    // Initial remote synchronization is intentionally started after mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadResources();
  }, [loadResources]);

  useEffect(() => {
    if (!gapsByChapter.length) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setExpandedChapter((current) => current || gapsByChapter[0][0]);
  }, [gapsByChapter]);

  useEffect(() => {
    if (!selectedGap) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedGap(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [selectedGap]);

  async function reloadAll() {
    await Promise.all([Promise.resolve(onReload()), loadResources()]);
  }

  function setSectionOpen(section: keyof typeof openSections, open: boolean) {
    setOpenSections((current) => current[section] === open ? current : { ...current, [section]: open });
  }

  const gapSummary = knowledgeGapSummary ?? {
    openCount: gaps.length,
    highCount: gaps.filter((gap) => gap.severity === "high").length,
    mediumCount: gaps.filter((gap) => gap.severity === "medium").length,
    lowCount: gaps.filter((gap) => gap.severity === "low").length,
    resolvedCount: 0,
  };
  const largestGapChapter = gapsByChapter
    .slice()
    .sort((left, right) => right[1].length - left[1].length)[0]?.[0];

  return (
    <div className="section-scroll user-center-page">
      <section className="user-center-shell">
        <header className="user-center-header">
          <div>
            <span className="eyebrow">LEARNER CENTER</span>
            <h2>用户中心</h2>
            <p>集中查看系统画像、知识漏洞、资源匹配与个性化学习设置。</p>
          </div>
          <button type="button" className="quiet-button" disabled={busy || resourceBusy} onClick={() => void reloadAll()}>
            {busy || resourceBusy ? "同步中…" : "同步最新数据"}
          </button>
        </header>

        <div className="user-center-content">
          <details
            className="user-center-disclosure overview"
            open={openSections.overview}
            onToggle={(event) => setSectionOpen("overview", event.currentTarget.open)}
          >
            <summary>
              <span className="user-center-disclosure-arrow" aria-hidden="true" />
              <span><strong>画像概览</strong><small>八维岗位能力画像</small></span>
              <em>{progress.provisionalMastery} 分</em>
            </summary>
            <div className="user-center-disclosure-body overview-radar-only">
              <section className="user-overview-capability">
                <UserCenterRadar items={radarItems} centerValue={capabilityOverall} />
              </section>
            </div>
          </details>

          <details
            className="user-center-disclosure"
            open={openSections.gaps}
            onToggle={(event) => setSectionOpen("gaps", event.currentTarget.open)}
          >
            <summary>
              <span className="user-center-disclosure-arrow" aria-hidden="true" />
              <span><strong>知识漏洞</strong><small>按课程章节聚合证据</small></span>
              <em>{gapSummary.openCount} 个待处理</em>
            </summary>
            <div className="user-center-disclosure-body">
            <section className="knowledge-gap-view">
              <div className="user-center-section-heading">
                <div>
                  <span className="eyebrow">KNOWLEDGE GAP MAP</span>
                  <h3>知识漏洞地图</h3>
                  <p>数据来自知识漏洞专用接口，按课程 Chapter 聚合并保留每条判断的证据入口。</p>
                </div>
              </div>
              <div className="gap-stat-strip">
                <div><span>待处理</span><strong>{gapSummary.openCount}</strong><small>未关闭的系统结论</small></div>
                <div><span>高优先级</span><strong>{gapSummary.highCount}</strong><small>建议优先补齐</small></div>
                <div><span>中 / 低优先级</span><strong>{gapSummary.mediumCount} / {gapSummary.lowCount}</strong><small>持续巩固与观察</small></div>
                <div><span>已解决</span><strong>{gapSummary.resolvedCount}</strong><small>后端历史累计</small></div>
                <div><span>最集中章节</span><strong>{largestGapChapter ? `Chapter ${largestGapChapter}` : "—"}</strong><small>{largestGapChapter ? CHAPTER_NAMES[largestGapChapter] : "暂无数据"}</small></div>
              </div>
              {gapsByChapter.length ? (
                <div className="gap-chapter-list">
                  {gapsByChapter.map(([chapter, chapterGaps]) => {
                    const open = expandedChapter === chapter;
                    return (
                      <section className={open ? "open" : ""} key={chapter}>
                        <button type="button" className="gap-chapter-trigger" onClick={() => setExpandedChapter(open ? "" : chapter)}>
                          <span className="gap-disclosure" aria-hidden="true">›</span>
                          <strong>{chapterTitle(chapter)}</strong>
                          <span>{chapterGaps.length} 个漏洞</span>
                        </button>
                        {open && (
                          <div className="gap-items">
                            {chapterGaps.map((gap) => (
                              <article className={`gap-item severity-${gap.severity}`} key={gap.id}>
                                <span className="gap-severity-dot" aria-hidden="true" />
                                <div>
                                  <div className="gap-item-title">
                                    <strong>{gap.concept}</strong>
                                    <span>{severityLabel(gap.severity)}</span>
                                  </div>
                                  <p>{gap.evidence}</p>
                                  <div className="gap-evidence-tags">
                                    <span>{CATEGORY_NAMES[gap.category] || gap.category}</span>
                                    <span>{gap.chapterId}</span>
                                    <span>{gap.evidenceItems.length || 1} 项证据</span>
                                    <span>评分 {Math.round(gap.score)}</span>
                                    <span>{shortDate(gap.updatedAt)}</span>
                                  </div>
                                </div>
                                <button type="button" onClick={() => setSelectedGap(gap)}>查看证据 →</button>
                              </article>
                            ))}
                          </div>
                        )}
                      </section>
                    );
                  })}
                </div>
              ) : (
                <div className="user-center-empty"><strong>暂未发现明确知识漏洞</strong><p>完成问答或 Quiz 后，后端 Memory 的结论会显示在这里。</p></div>
              )}
            </section>
            </div>
          </details>

          <details
            className="user-center-disclosure"
            open={openSections.matching}
            onToggle={(event) => setSectionOpen("matching", event.currentTarget.open)}
          >
            <summary>
              <span className="user-center-disclosure-arrow" aria-hidden="true" />
              <span><strong>资源匹配</strong><small>资源难度与当前能力对照</small></span>
              <em>{overallAlignment === null ? "等待数据" : `${overallAlignment}% 匹配`}</em>
            </summary>
            <div className="user-center-disclosure-body">
            <section className="resource-matching-view">
              <div className="resource-match-toolbar">
                <div className="user-center-section-heading">
                  <div>
                    <span className="eyebrow">DIFFICULTY ALIGNMENT</span>
                    <h3>资源难度与用户匹配曲线</h3>
                    <p>蓝线来自资源难度记录，绿线来自同次记录中的用户能力分数。</p>
                  </div>
                </div>
                <label>
                  <span>查看章节</span>
                  <select value={selectedResourceChapter} onChange={(event) => setSelectedResourceChapter(event.target.value)}>
                    <option value="">全部 Chapter</option>
                    {resourceChapters.map((chapter) => (
                      <option value={chapter} key={chapter}>{chapterTitle(chapter)}</option>
                    ))}
                  </select>
                </label>
                <div className="overall-alignment">
                  <span>当前总体匹配度</span>
                  <strong>{overallAlignment === null ? "—" : `${overallAlignment}%`}</strong>
                </div>
                <div className="overall-alignment profile-score">
                  <span>后端当前画像分</span>
                  <strong>{resourceProfileScore === null ? "—" : Math.round(resourceProfileScore)}</strong>
                </div>
              </div>
              {resourceError ? (
                <div className="user-center-empty error"><strong>资源匹配记录读取失败</strong><p>{resourceError}</p><button type="button" onClick={() => void loadResources()}>重新读取</button></div>
              ) : visibleResourceRecords.length ? (
                <>
                  <ResourceMatchChart records={visibleResourceRecords} />
                  <div className="resource-attention-list">
                    <div>
                      <h4>资源判断</h4>
                      <p>差值在 ±10 分内为匹配；超过范围时给出巩固或进阶建议。</p>
                    </div>
                    {visibleResourceRecords.map((record) => {
                      const verdict = matchingVerdict(record.difficulty_delta);
                      return (
                        <article className={verdict.tone} key={record.record_id}>
                          <div><strong>{resourceTitle(record)}</strong><span>{verdict.advice}</span><small>{RESOURCE_TYPE_NAMES[record.resource_type] || record.resource_type} · {record.source_node || "后端记录"} · {shortDate(record.created_at || "")}</small></div>
                          <span>{Math.round(record.resource_difficulty)} / {Math.round(record.profile_score)}</span>
                          <em>{verdict.label}</em>
                        </article>
                      );
                    })}
                  </div>
                </>
              ) : (
                <div className="user-center-empty"><strong>{resourceBusy ? "正在读取资源匹配记录…" : "暂无资源匹配记录"}</strong><p>生成讲义、Quiz 或实训练习后，后端记录的真实难度匹配数据会显示在这里。</p></div>
              )}
            </section>
            </div>
          </details>

          <details
            className="user-center-disclosure custom"
            open={openSections.custom}
            onToggle={(event) => setSectionOpen("custom", event.currentTarget.open)}
          >
            <summary>
              <span className="user-center-disclosure-arrow" aria-hidden="true" />
              <span><strong>自定义画像</strong><small>直接查看并编辑当前用户的 profile.md</small></span>
              <em>Markdown</em>
            </summary>
            <div className="user-center-disclosure-body">
            <section className="custom-profile-view">
              <ProfileMarkdownEditor key={userId} userId={userId} />
            </section>
            </div>
          </details>
        </div>
      </section>

      {selectedGap && (
        <div className="gap-drawer-backdrop" role="presentation" onMouseDown={() => setSelectedGap(null)}>
          <aside className="gap-evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="gap-evidence-title" onMouseDown={(event) => event.stopPropagation()}>
            <header>
              <div><span>{severityLabel(selectedGap.severity)}</span><h3 id="gap-evidence-title">{selectedGap.concept}</h3></div>
              <button type="button" aria-label="关闭知识漏洞证据" onClick={() => setSelectedGap(null)}>×</button>
            </header>
            <div className="gap-drawer-content">
              <section><h4>Memory 结论原文</h4><p>{selectedGap.evidence}</p></section>
              <section>
                <h4>证据来源</h4>
                {selectedGap.evidenceItems.length ? selectedGap.evidenceItems.map((item, index) => (
                  <article className="gap-source-item" key={`${selectedGap.id}-evidence-${index}`}>
                    <strong>{stringValue(item.source_type ?? item.type, `证据 ${index + 1}`)}</strong>
                    <p>{stringValue(item.summary ?? item.text ?? item.evidence, "后端未提供可读摘要")}</p>
                    <span>{stringValue(item.created_at ?? item.time)}</span>
                  </article>
                )) : <p className="gap-drawer-muted">该条记录仅保存了综合结论，尚无拆分后的证据明细。</p>}
              </section>
              {selectedGap.recommendedActions.length > 0 && (
                <section><h4>建议行动</h4><ol>{selectedGap.recommendedActions.map((action) => <li key={action}>{action}</li>)}</ol></section>
              )}
              <dl className="gap-record-meta">
                <div><dt>Memory Entry ID</dt><dd>{selectedGap.id}</dd></div>
                <div><dt>知识点</dt><dd>{selectedGap.knowledgePointId || selectedGap.chapterId}</dd></div>
                <div><dt>优先级 / 评分</dt><dd>{severityLabel(selectedGap.severity)} · {Math.round(selectedGap.score)}</dd></div>
                <div><dt>状态</dt><dd>{selectedGap.status}</dd></div>
                <div><dt>来源</dt><dd>{selectedGap.source}</dd></div>
                <div><dt>更新时间</dt><dd>{shortDate(selectedGap.updatedAt)}</dd></div>
              </dl>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
