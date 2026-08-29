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

type SelfLevelChoice = "beginner" | "intermediate" | "proficient" | "expert";

type CustomProfileDraft = {
  profession: string;
  foundations: string[];
  about: string;
  level: SelfLevelChoice;
  goals: string[];
  goalOther: string;
  learningStyles: string[];
  learningOther: string;
  answerDetail: string;
  contentDifficulty: string;
  quizPreferences: string[];
  lecturePreferences: string[];
  avoidances: string[];
  avoidanceOther: string;
};

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

const PROFESSION_OPTIONS = ["机械类", "自动化类", "计算机类", "其他"];
const FOUNDATION_OPTIONS = ["机械制图", "编程基础", "加工工艺", "机床实操经验"];
const GOAL_OPTIONS = ["掌握课程基础知识", "应对课程考试", "提高实际操作能力", "准备比赛/项目", "岗位能力提升", "其他"];
const LEARNING_STYLE_OPTIONS = ["步骤化讲解", "先举例", "少术语", "图示辅助", "先讲结论", "深入讲原理", "联系实际", "多做练习"];
const QUIZ_PREFERENCE_OPTIONS = ["从易到难", "每题给解析", "优先薄弱知识点"];
const LECTURE_PREFERENCE_OPTIONS = ["多举例", "分步骤", "增加总结", "增加理论推导"];
const AVOIDANCE_OPTIONS = ["大量未经解释的专业术语", "跳过中间步骤", "过多基础解释", "直接给答案", "过长背景介绍"];

const SELF_LEVEL_OPTIONS: Array<{ id: SelfLevelChoice; title: string; detail: string; backend: LearnerProfile["level"] }> = [
  { id: "beginner", title: "初学者", detail: "从零开始", backend: "beginner" },
  { id: "intermediate", title: "有基础", detail: "了解主要概念", backend: "intermediate" },
  { id: "proficient", title: "熟练", detail: "能够独立应用", backend: "advanced" },
  { id: "expert", title: "高阶", detail: "希望深入学习", backend: "advanced" },
];

function selectedFromText(text: string, options: string[]): string[] {
  return options.filter((option) => text.includes(option));
}

function textAfterLabel(text: string, label: string): string {
  const match = text.match(new RegExp(`${label}：([^；]*)`));
  return match?.[1]?.trim() || "";
}

function createCustomProfileDraft(profile: LearnerProfile): CustomProfileDraft {
  const background = String(profile.background || "");
  const preference = String(profile.preference || "");
  const profession = PROFESSION_OPTIONS.find((option) => background.includes(option.replace("类", ""))) || "其他";
  const hasStructuredBackground = background.includes("专业背景：") || background.includes("已有基础：") || background.includes("补充：");
  const level: SelfLevelChoice = profile.level === "beginner"
    ? "beginner"
    : profile.level === "intermediate"
      ? "intermediate"
      : preference.includes("自评定位：高阶")
        ? "expert"
        : "proficient";
  return {
    profession,
    foundations: selectedFromText(background, FOUNDATION_OPTIONS),
    about: hasStructuredBackground ? textAfterLabel(background, "补充") : (profession === "其他" ? background : ""),
    level,
    goals: selectedFromText(preference, GOAL_OPTIONS),
    goalOther: textAfterLabel(preference, "其他学习目标"),
    learningStyles: LEARNING_STYLE_OPTIONS.filter((option) =>
      preference.includes(option) || (option === "步骤化讲解" && preference.includes("步骤化")),
    ),
    learningOther: preference.includes("学习方式：") ? textAfterLabel(preference, "其他讲解要求") : preference,
    answerDetail: ["简洁", "适中", "详细"].find((option) => preference.includes(`回答详细度：${option}`)) || "适中",
    contentDifficulty: ["自动匹配", "偏基础", "偏进阶"].find((option) => preference.includes(`内容难度：${option}`)) || "自动匹配",
    quizPreferences: selectedFromText(preference, QUIZ_PREFERENCE_OPTIONS),
    lecturePreferences: selectedFromText(preference, LECTURE_PREFERENCE_OPTIONS),
    avoidances: selectedFromText(preference, AVOIDANCE_OPTIONS),
    avoidanceOther: textAfterLabel(preference, "其他避免内容"),
  };
}

function composeProfile(draft: CustomProfileDraft): LearnerProfile {
  const selectedLevel = SELF_LEVEL_OPTIONS.find((option) => option.id === draft.level) || SELF_LEVEL_OPTIONS[0];
  const background = [
    `专业背景：${draft.profession}`,
    draft.foundations.length ? `已有基础：${draft.foundations.join("、")}` : "",
    draft.about.trim() ? `补充：${draft.about.trim()}` : "",
  ].filter(Boolean).join("；");
  const preference = [
    draft.level === "expert" ? "自评定位：高阶" : "",
    draft.goals.length ? `学习目标：${draft.goals.filter((item) => item !== "其他").join("、")}` : "",
    draft.goals.includes("其他") && draft.goalOther.trim() ? `其他学习目标：${draft.goalOther.trim()}` : "",
    draft.learningStyles.length ? `学习方式：${draft.learningStyles.join("、")}` : "",
    draft.learningOther.trim() ? `其他讲解要求：${draft.learningOther.trim()}` : "",
    `回答详细度：${draft.answerDetail}`,
    `内容难度：${draft.contentDifficulty}`,
    draft.quizPreferences.length ? `Quiz：${draft.quizPreferences.join("、")}` : "",
    draft.lecturePreferences.length ? `讲义：${draft.lecturePreferences.join("、")}` : "",
    draft.avoidances.length ? `不希望出现：${draft.avoidances.join("、")}` : "",
    draft.avoidanceOther.trim() ? `其他避免内容：${draft.avoidanceOther.trim()}` : "",
  ].filter(Boolean).join("；");
  return { background, level: selectedLevel.backend, preference };
}

function toggleSelection(items: string[], value: string): string[] {
  return items.includes(value) ? items.filter((item) => item !== value) : [...items, value];
}

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
  setProfile,
  knowledgeGaps,
  knowledgeGapSummary,
  busy,
  onReload,
  onSaved,
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
  const [customDraft, setCustomDraft] = useState(() => createCustomProfileDraft(profile));
  const originalCustomDraft = useMemo(() => createCustomProfileDraft(profile), [profile]);

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
  const draftProfile = useMemo(() => composeProfile(customDraft), [customDraft]);
  const profileChanged = JSON.stringify(customDraft) !== JSON.stringify(originalCustomDraft);
  const profileCompletion = useMemo(() => {
    const completed = [
      Boolean(customDraft.profession),
      customDraft.foundations.length > 0 || Boolean(customDraft.about.trim()),
      Boolean(customDraft.level),
      customDraft.goals.length > 0,
      customDraft.learningStyles.length > 0,
      Boolean(customDraft.answerDetail && customDraft.contentDifficulty),
      customDraft.quizPreferences.length > 0 || customDraft.lecturePreferences.length > 0,
      customDraft.avoidances.length > 0 || Boolean(customDraft.avoidanceOther.trim()),
    ].filter(Boolean).length;
    return Math.round((completed / 8) * 100);
  }, [customDraft]);

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
    // The editable draft mirrors backend updates until the learner starts editing.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCustomDraft(createCustomProfileDraft(profile));
  }, [profile]);

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

  async function saveProfileDraft() {
    setProfile(draftProfile);
    await onSaved(draftProfile);
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
              <span><strong>自定义画像</strong><small>调整知链的个性化学习方式</small></span>
              <em>{profileCompletion}% 完成</em>
            </summary>
            <div className="user-center-disclosure-body">
            <section className="custom-profile-view">
              <div className="custom-profile-intro">
                <div>
                  <span className="eyebrow">CUSTOM INSTRUCTIONS</span>
                  <h3>让知链更了解你</h3>
                  <p>能选择的信息无需手动填写；只有个性化情况保留简短补充。</p>
                </div>
                <div className="profile-completion" aria-label={`画像完成度 ${profileCompletion}%`}>
                  <span>画像完成度</span>
                  <strong>{profileCompletion}%</strong>
                  <i><b style={{ width: `${profileCompletion}%` }} /></i>
                </div>
              </div>
              <div className="custom-profile-workspace">
                <div className="custom-profile-sections">
                  <section className="custom-setting-section">
                    <header><span>01</span><div><h4>关于我</h4><p>选择专业与已有基础，再按需补充个人情况。</p></div></header>
                    <div className="custom-setting-body">
                      <fieldset><legend>专业背景 · 单选</legend><div className="profile-choice-row single">
                        {PROFESSION_OPTIONS.map((option) => <button type="button" aria-pressed={customDraft.profession === option} className={customDraft.profession === option ? "selected" : ""} onClick={() => setCustomDraft((current) => ({ ...current, profession: option }))} key={option}>{option}</button>)}
                      </div></fieldset>
                      <fieldset><legend>已有基础 · 可多选</legend><div className="profile-choice-row">
                        {FOUNDATION_OPTIONS.map((option) => <button type="button" aria-pressed={customDraft.foundations.includes(option)} className={customDraft.foundations.includes(option) ? "selected" : ""} onClick={() => setCustomDraft((current) => ({ ...current, foundations: toggleSelection(current.foundations, option) }))} key={option}>{option}</button>)}
                      </div></fieldset>
                      <label className="compact-profile-input"><span>补充说明 <small>可选</small></span><textarea value={customDraft.about} maxLength={500} placeholder="例如：没有实际操作过数控机床，但有 C 语言基础。" onChange={(event) => setCustomDraft((current) => ({ ...current, about: event.target.value }))} /><em>{customDraft.about.length}/500</em></label>
                    </div>
                  </section>

                  <section className="custom-setting-section">
                    <header><span>02</span><div><h4>当前自评水平</h4><p>仅用于调整内容难度，不会直接改变能力评分。</p></div></header>
                    <div className="level-choice-grid">
                      {SELF_LEVEL_OPTIONS.map((option) => <button type="button" aria-pressed={customDraft.level === option.id} className={customDraft.level === option.id ? "selected" : ""} onClick={() => setCustomDraft((current) => ({ ...current, level: option.id }))} key={option.id}><strong>{option.title}</strong><span>{option.detail}</span><i aria-hidden="true">✓</i></button>)}
                    </div>
                  </section>

                  <section className="custom-setting-section">
                    <header><span>03</span><div><h4>当前学习目标</h4><p>选择一个或多个近期目标。</p></div></header>
                    <div className="custom-setting-body"><div className="profile-choice-row">
                      {GOAL_OPTIONS.map((option) => <button type="button" aria-pressed={customDraft.goals.includes(option)} className={customDraft.goals.includes(option) ? "selected" : ""} onClick={() => setCustomDraft((current) => ({ ...current, goals: toggleSelection(current.goals, option) }))} key={option}>{option}</button>)}
                    </div>{customDraft.goals.includes("其他") && <label className="inline-profile-input"><span>其他目标</span><input value={customDraft.goalOther} maxLength={100} placeholder="补充你的学习目标" onChange={(event) => setCustomDraft((current) => ({ ...current, goalOther: event.target.value }))} /></label>}</div>
                  </section>

                  <section className="custom-setting-section">
                    <header><span>04</span><div><h4>我喜欢怎样学习</h4><p>这些偏好会影响回答、Quiz 解析和讲义表达。</p></div></header>
                    <div className="custom-setting-body"><div className="profile-choice-row">
                      {LEARNING_STYLE_OPTIONS.map((option) => <button type="button" aria-pressed={customDraft.learningStyles.includes(option)} className={customDraft.learningStyles.includes(option) ? "selected" : ""} onClick={() => setCustomDraft((current) => ({ ...current, learningStyles: toggleSelection(current.learningStyles, option) }))} key={option}>{option}</button>)}
                    </div><label className="inline-profile-input"><span>其他讲解要求 <small>可选</small></span><input value={customDraft.learningOther} maxLength={160} placeholder="例如：关键步骤附上容易犯错的原因" onChange={(event) => setCustomDraft((current) => ({ ...current, learningOther: event.target.value }))} /></label></div>
                  </section>

                  <section className="custom-setting-section">
                    <header><span>05</span><div><h4>内容生成偏好</h4><p>用选择项控制回答、Quiz 与讲义的默认呈现。</p></div></header>
                    <div className="custom-setting-body content-preference-grid">
                      <fieldset><legend>回答详细度</legend><div className="profile-segmented-control">{["简洁", "适中", "详细"].map((option) => <button type="button" aria-pressed={customDraft.answerDetail === option} className={customDraft.answerDetail === option ? "selected" : ""} onClick={() => setCustomDraft((current) => ({ ...current, answerDetail: option }))} key={option}>{option}</button>)}</div></fieldset>
                      <fieldset><legend>默认内容难度</legend><div className="profile-segmented-control">{["自动匹配", "偏基础", "偏进阶"].map((option) => <button type="button" aria-pressed={customDraft.contentDifficulty === option} className={customDraft.contentDifficulty === option ? "selected" : ""} onClick={() => setCustomDraft((current) => ({ ...current, contentDifficulty: option }))} key={option}>{option}</button>)}</div></fieldset>
                      <fieldset className="wide"><legend>Quiz 偏好 · 可多选</legend><div className="profile-choice-row">{QUIZ_PREFERENCE_OPTIONS.map((option) => <button type="button" aria-pressed={customDraft.quizPreferences.includes(option)} className={customDraft.quizPreferences.includes(option) ? "selected" : ""} onClick={() => setCustomDraft((current) => ({ ...current, quizPreferences: toggleSelection(current.quizPreferences, option) }))} key={option}>{option}</button>)}</div></fieldset>
                      <fieldset className="wide"><legend>讲义偏好 · 可多选</legend><div className="profile-choice-row">{LECTURE_PREFERENCE_OPTIONS.map((option) => <button type="button" aria-pressed={customDraft.lecturePreferences.includes(option)} className={customDraft.lecturePreferences.includes(option) ? "selected" : ""} onClick={() => setCustomDraft((current) => ({ ...current, lecturePreferences: toggleSelection(current.lecturePreferences, option) }))} key={option}>{option}</button>)}</div></fieldset>
                    </div>
                  </section>

                  <section className="custom-setting-section">
                    <header><span>06</span><div><h4>我不希望出现</h4><p>提前说明需要避免的表达方式。</p></div></header>
                    <div className="custom-setting-body"><div className="profile-choice-row avoidance">
                      {AVOIDANCE_OPTIONS.map((option) => <button type="button" aria-pressed={customDraft.avoidances.includes(option)} className={customDraft.avoidances.includes(option) ? "selected" : ""} onClick={() => setCustomDraft((current) => ({ ...current, avoidances: toggleSelection(current.avoidances, option) }))} key={option}>{option}</button>)}
                    </div><label className="inline-profile-input"><span>其他不希望出现的内容 <small>可选</small></span><input value={customDraft.avoidanceOther} maxLength={160} placeholder="补充特殊要求" onChange={(event) => setCustomDraft((current) => ({ ...current, avoidanceOther: event.target.value }))} /></label></div>
                  </section>
                </div>

                <aside className="profile-live-preview">
                  <span className="eyebrow">LIVE PREVIEW</span>
                  <h4>知链将这样帮助你</h4>
                  <p>{customDraft.profession || "未选择专业"} · {SELF_LEVEL_OPTIONS.find((option) => option.id === customDraft.level)?.title}</p>
                  <dl>
                    <div><dt>当前目标</dt><dd>{customDraft.goals.filter((item) => item !== "其他").join("、") || customDraft.goalOther || "等待选择"}</dd></div>
                    <div><dt>讲解方式</dt><dd>{customDraft.learningStyles.join("、") || "采用系统默认方式"}</dd></div>
                    <div><dt>内容设置</dt><dd>{customDraft.answerDetail}回答 · {customDraft.contentDifficulty}</dd></div>
                    <div><dt>重点避免</dt><dd>{customDraft.avoidances.join("、") || "暂无特殊限制"}</dd></div>
                  </dl>
                  <div className="profile-preview-example"><span>回答示例</span><p>{customDraft.learningStyles.includes("先讲结论") ? "先给出核心结论，" : ""}{customDraft.learningStyles.includes("先举例") ? "从实际案例开始，" : ""}{customDraft.learningStyles.includes("步骤化讲解") ? "再按步骤拆解操作。" : "再清楚解释关键知识。"}</p></div>
                  <div className="custom-profile-boundary"><strong>与系统画像相互独立</strong><span>可编辑：以上学习偏好</span><span>只读：能力分数、Quiz、知识漏洞与证据结论</span></div>
                </aside>
              </div>
            </section>
            </div>
          </details>
        </div>
      </section>

      {profileChanged && (
        <div className="profile-save-bar" role="status">
          <span><i />有未保存的修改</span>
          <div>
            <button type="button" disabled={busy} onClick={() => setCustomDraft(createCustomProfileDraft(profile))}>取消</button>
            <button type="button" className="primary" disabled={busy} onClick={() => void saveProfileDraft()}>{busy ? "保存中…" : "保存更改"}</button>
          </div>
        </div>
      )}

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
