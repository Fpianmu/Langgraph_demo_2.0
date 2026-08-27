import type {
  AgentResponse,
  LearnerProfile,
  ScoreMap,
} from "@/lib/agent-contract";
import {
  CAPABILITY_DIMENSIONS,
  type CapabilityDimensionId,
} from "./capability-assessment.ts";

export type MemorySignal = {
  title: string;
  detail: string;
};

export type RecommendationOrigin = "domain-default" | "memory" | "rag";

export type QuizRecommendation = {
  id: string;
  topic: string;
  focus: string;
  reason: string;
};

export type LearningRecommendations = {
  chatPrompts: string[];
  quizOptions: QuizRecommendation[];
  primaryTopic: string;
  contextLabel: string;
  origin: RecommendationOrigin;
};

type RecommendationContext = {
  profile: LearnerProfile;
  scores: ScoreMap;
  memoryEvents?: MemorySignal[];
  /**
   * Optional today, ready for the future RAG connection. Once the
   * orchestrator returns grounded evidence, its query/document names/text are
   * folded into the same ranking instead of creating a second recommendation
   * system.
   */
  ragPackage?: AgentResponse["rag_package"];
};

type LearningTrack = {
  id: string;
  label: string;
  scoreDimension: CapabilityDimensionId;
  keywords: string[];
  chatTask: string;
  quizTopic: string;
  quizFocus: string;
  defaultPriority: number;
};

const CNC_TRACKS: LearningTrack[] = [
  {
    id: "safety",
    label: "数控机床安全操作",
    scoreDimension: "safety",
    keywords: [
      "安全",
      "急停",
      "防护",
      "事故",
      "风险",
      "违规",
      "操作规程",
      "开机检查",
    ],
    chatTask:
      "讲清数控机床开机前检查、个人防护、急停操作和异常情况处置",
    quizTopic: "数控机床安全操作",
    quizFocus: "开机前检查、个人防护、急停操作、异常报警与规范处置",
    defaultPriority: 1.2,
  },
  {
    id: "operation",
    label: "数控车铣基本操作",
    scoreDimension: "machining_operation",
    keywords: [
      "操作",
      "装夹",
      "对刀",
      "刀具",
      "首件",
      "试切",
      "机床",
      "车削",
      "铣削",
    ],
    chatTask:
      "说明数控车铣加工从工件装夹、刀具安装、对刀到首件试切的标准流程",
    quizTopic: "数控车铣加工基本操作",
    quizFocus: "工件装夹、刀具安装、对刀、程序校验、空运行与首件试切",
    defaultPriority: 1.1,
  },
  {
    id: "theory",
    label: "数控加工基础理论",
    scoreDimension: "foundations",
    keywords: [
      "理论",
      "坐标系",
      "切削参数",
      "刀具补偿",
      "工艺",
      "公差",
      "测量",
      "基础知识",
    ],
    chatTask:
      "解释数控加工坐标系、刀具补偿、切削用量与加工精度之间的关系",
    quizTopic: "数控加工基础理论",
    quizFocus: "机床坐标系、工件坐标系、刀具补偿、切削参数与尺寸精度",
    defaultPriority: 1,
  },
  {
    id: "programming",
    label: "数控编程与程序校验",
    scoreDimension: "programming",
    keywords: [
      "编程",
      "程序",
      "g代码",
      "m代码",
      "g-code",
      "m-code",
      "循环指令",
      "仿真",
      "程序校验",
    ],
    chatTask:
      "结合简单加工案例解释常用 G/M 代码、程序结构和程序校验方法",
    quizTopic: "数控加工程序编制与校验",
    quizFocus: "程序结构、常用 G/M 指令、刀具补偿、循环指令与程序校验",
    defaultPriority: 0.9,
  },
  {
    id: "multiaxis",
    label: "多轴数控加工",
    scoreDimension: "advanced_manufacturing",
    keywords: [
      "多轴",
      "五轴",
      "四轴",
      "联动",
      "旋转轴",
      "刀轴",
      "后处理",
      "碰撞",
    ],
    chatTask:
      "对比三轴与多轴加工，说明旋转轴、联动加工、后处理和防碰撞要点",
    quizTopic: "多轴数控加工基础",
    quizFocus: "旋转轴定义、坐标变换、联动加工、后处理与碰撞检查",
    defaultPriority: 0.8,
  },
  {
    id: "certificate",
    label: "职业技能等级考核",
    scoreDimension: "process_planning",
    keywords: [
      "证书",
      "考核",
      "考试",
      "职业标准",
      "初级",
      "中级",
      "高级",
      "题库",
      "复习",
    ],
    chatTask:
      "梳理数控车铣加工职业技能等级考核的知识要求、技能要求和复习重点",
    quizTopic: "数控车铣加工职业技能等级考核",
    quizFocus: "安全规范、基础理论、程序编制、操作流程与质量检测",
    defaultPriority: 0.7,
  },
];

function normalize(value: unknown): string {
  return String(value ?? "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function profileText(profile: LearnerProfile): string {
  return Object.values(profile)
    .flatMap((value) => (Array.isArray(value) ? value : [value]))
    .map(normalize)
    .filter(Boolean)
    .join(" ");
}

function memoryText(events: MemorySignal[]): string {
  return events
    .slice(0, 12)
    .flatMap((event) => [event.title, event.detail])
    .map(normalize)
    .filter(Boolean)
    .join(" ");
}

function ragText(ragPackage: AgentResponse["rag_package"]): string {
  if (!ragPackage) return "";
  return [
    ragPackage.query,
    ragPackage.answer,
    ...(ragPackage.evidence ?? []).flatMap((item) => [
      item.source_file ?? item.source_doc,
      item.text,
    ]),
  ]
    .map(normalize)
    .filter(Boolean)
    .join(" ");
}

function keywordHits(text: string, keywords: string[]): number {
  if (!text) return 0;
  return keywords.reduce((total, keyword) => {
    const token = normalize(keyword);
    if (!token) return total;
    return total + (text.includes(token) ? 1 : 0);
  }, 0);
}

function clampScore(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 60;
  return Math.max(0, Math.min(100, numeric));
}

function scoreLabel(id: CapabilityDimensionId): string {
  return (
    CAPABILITY_DIMENSIONS.find((dimension) => dimension.id === id)?.shortLabel ||
    id
  );
}

function learningStyle(profile: LearnerProfile): string {
  const preference = String(profile.preference ?? "").trim().slice(0, 32);
  if (preference) return `请按“${preference}”的方式，`;
  if (profile.level === "advanced") return "请结合职业标准和典型案例，";
  if (profile.level === "intermediate") return "请结合一个典型加工案例，";
  return "请从基础开始、分步骤地，";
}

function difficultyHint(level: LearnerProfile["level"]): string {
  if (level === "advanced") return "进阶应用与综合判断";
  if (level === "intermediate") return "概念理解与典型应用";
  return "核心概念与规范操作";
}

function displaySourceName(source: string | undefined): string | null {
  if (!source) return null;
  const name = source
    .split(/[\\/]/)
    .pop()
    ?.replace(/\.(pdf|docx?|xlsx?|pptx?|txt|md)$/i, "")
    .replace(/[_-]+/g, " ")
    .trim();
  if (!name) return null;
  return name.slice(0, 48);
}

function ragSourceName(
  ragPackage: AgentResponse["rag_package"],
): string | null {
  const evidence = [...(ragPackage?.evidence ?? [])].sort(
    (a, b) => Number(b.score ?? 0) - Number(a.score ?? 0),
  );
  return displaySourceName(
    evidence[0]?.source_file ?? evidence[0]?.source_doc,
  );
}

/**
 * Build deterministic, domain-safe recommendations.
 *
 * - Without RAG: recommendations stay inside the CNC/multi-axis curriculum.
 * - As Memory changes: weak score dimensions and remembered topic words alter
 *   ordering, wording, quiz topic, focus and difficulty.
 * - With RAG later: retrieved document names and evidence add a grounded first
 *   option while the CNC fallback remains available.
 */
export function buildLearningRecommendations({
  profile,
  scores,
  memoryEvents = [],
  ragPackage = null,
}: RecommendationContext): LearningRecommendations {
  const remembered = `${profileText(profile)} ${memoryText(memoryEvents)}`;
  const retrieved = ragText(ragPackage);
  const style = learningStyle(profile);

  const ranked = CNC_TRACKS.map((track, index) => {
    const memoryHits = keywordHits(remembered, track.keywords);
    const ragHits = keywordHits(retrieved, track.keywords);
    const gap = 100 - clampScore(scores[track.scoreDimension]);
    const rank =
      track.defaultPriority +
      gap / 18 +
      memoryHits * 3.5 +
      ragHits * 4.5 -
      index * 0.001;
    return { track, rank, memoryHits, ragHits };
  }).sort((a, b) => b.rank - a.rank);

  const sourceName = ragSourceName(ragPackage);
  const anyRagSignal = ranked.some((item) => item.ragHits > 0) || !!sourceName;
  const anyMemoryTopic = ranked.some((item) => item.memoryHits > 0);
  const origin: RecommendationOrigin = anyRagSignal
    ? "rag"
    : anyMemoryTopic
      ? "memory"
      : "domain-default";

  const weakest = ranked[0].track;
  const weakestScore = Math.round(clampScore(scores[weakest.scoreDimension]));
  const contextLabel = anyRagSignal
    ? `已结合 Memory 与知识资料，当前优先：${weakest.label}`
    : `已根据 Memory 调整，当前优先：${weakest.label}（${weakestScore} 分）`;

  const chatPrompts = ranked.slice(0, 4).map(({ track }) =>
    `${style}${track.chatTask}`,
  );

  const quizOptions: QuizRecommendation[] = ranked.slice(0, 3).map(
    ({ track, memoryHits, ragHits }) => ({
      id: track.id,
      topic: track.quizTopic,
      focus: `${track.quizFocus}；${difficultyHint(profile.level)}`,
      reason:
        ragHits > 0
          ? "匹配当前知识资料"
          : memoryHits > 0
            ? "匹配近期 Memory"
            : `${scoreLabel(track.scoreDimension)} ${Math.round(clampScore(scores[track.scoreDimension]))} 分`,
    }),
  );

  if (sourceName) {
    const documentPrompt = `${style}结合《${sourceName}》梳理与我当前薄弱项相关的重点，并给出复习顺序`;
    chatPrompts.unshift(documentPrompt);
    chatPrompts.splice(4);
    quizOptions.unshift({
      id: `rag-${sourceName}`,
      topic: sourceName,
      focus: `严格依据《${sourceName}》考查核心概念、规范要求与实际应用`,
      reason: "来自当前知识资料",
    });
    quizOptions.splice(3);
  }

  return {
    chatPrompts,
    quizOptions,
    primaryTopic: quizOptions[0].topic,
    contextLabel,
    origin,
  };
}
