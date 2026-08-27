import type { ScoreMap } from "./agent-contract.ts";
import {
  CAPABILITY_DIMENSIONS,
  type AssessmentDifficulty,
  type CapabilityDimensionId,
} from "./capability-assessment.ts";

export const DEFAULT_QUIZ_QUESTION_COUNT = 50;
export const MIN_QUIZ_QUESTION_COUNT = 8;
export const MAX_QUIZ_QUESTION_COUNT = 50;
export const QUIZ_GENERATION_BATCH_SIZE = 10;

export type QuizQuestionType =
  | "single_choice"
  | "true_false"
  | "cloze"
  | "short_answer";

export type QuizBlueprintItem = {
  sequence: number;
  questionType: QuizQuestionType;
  difficulty: AssessmentDifficulty;
  capabilityDimension: CapabilityDimensionId;
  points: number;
};

export type QuizBlueprintSummary = {
  total: number;
  byType: Record<QuizQuestionType, number>;
  byDifficulty: Record<AssessmentDifficulty, number>;
  byDimension: Record<CapabilityDimensionId, number>;
  totalPoints: number;
};

const TYPE_RATIOS: Record<QuizQuestionType, number> = {
  single_choice: 0.44,
  true_false: 0.16,
  cloze: 0.2,
  short_answer: 0.2,
};

const DIFFICULTY_RATIOS: Record<AssessmentDifficulty, number> = {
  easy: 0.3,
  medium: 0.5,
  hard: 0.2,
};

export const QUIZ_TYPE_LABELS: Record<QuizQuestionType, string> = {
  single_choice: "单项选择题",
  true_false: "判断题",
  cloze: "知识点填空",
  short_answer: "简答题",
};

export const QUIZ_DIFFICULTY_LABELS: Record<AssessmentDifficulty, string> = {
  easy: "基础",
  medium: "中等",
  hard: "进阶",
};

/** Stable paper order: objective questions first, then subjective questions. */
export const QUIZ_TYPE_ORDER: QuizQuestionType[] = [
  "single_choice",
  "true_false",
  "cloze",
  "short_answer",
];

function allocateByRatio<T extends string>(
  total: number,
  ratios: Record<T, number>,
): Record<T, number> {
  const entries = Object.entries(ratios) as Array<[T, number]>;
  const allocation = Object.fromEntries(
    entries.map(([key, ratio]) => [key, Math.floor(total * ratio)]),
  ) as Record<T, number>;
  const remaining =
    total -
    (Object.values(allocation) as number[]).reduce(
      (sum, value) => sum + value,
      0,
    );
  const ranked = entries
    .map(([key, ratio], index) => ({
      key,
      index,
      remainder: total * ratio - Math.floor(total * ratio),
    }))
    .sort((a, b) => b.remainder - a.remainder || a.index - b.index);
  for (let index = 0; index < remaining; index += 1) {
    allocation[ranked[index % ranked.length].key] += 1;
  }
  return allocation;
}

function expandAllocation<T extends string>(allocation: Record<T, number>): T[] {
  return (Object.entries(allocation) as Array<[T, number]>).flatMap(([key, count]) =>
    Array.from({ length: count }, () => key),
  );
}

function safeScore(scores: ScoreMap, dimension: CapabilityDimensionId): number {
  const raw = Number(scores[dimension]);
  return Number.isFinite(raw) ? Math.max(0, Math.min(100, raw)) : 50;
}

function dimensionOrder(scores: ScoreMap): CapabilityDimensionId[] {
  return [...CAPABILITY_DIMENSIONS]
    .sort((a, b) => safeScore(scores, a.id) - safeScore(scores, b.id))
    .map((item) => item.id);
}

function allocateDimensions(
  total: number,
  scores: ScoreMap,
): Record<CapabilityDimensionId, number> {
  const ordered = dimensionOrder(scores);
  const allocation = Object.fromEntries(
    ordered.map((dimension) => [dimension, 1]),
  ) as Record<CapabilityDimensionId, number>;
  let remaining = total - ordered.length;
  let cursor = 0;
  // Every dimension receives one item. Additional items are distributed with
  // a 2:1 bias toward weaker dimensions while still maintaining broad coverage.
  const weightedOrder = [...ordered, ...ordered.slice(0, 4)];
  while (remaining > 0) {
    allocation[weightedOrder[cursor % weightedOrder.length]] += 1;
    cursor += 1;
    remaining -= 1;
  }
  return allocation;
}

function orderedDifficulties(total: number): AssessmentDifficulty[] {
  const counts = allocateByRatio(total, DIFFICULTY_RATIOS);
  const result: AssessmentDifficulty[] = [];
  // A paper starts with accessible questions and gradually raises cognitive
  // demand, but medium/hard items are interleaved to avoid one abrupt block.
  for (let index = 0; index < total; index += 1) {
    const progress = total <= 1 ? 0 : index / (total - 1);
    const preference: AssessmentDifficulty[] =
      progress < 0.35
        ? ["easy", "medium", "hard"]
        : progress < 0.75
          ? ["medium", "easy", "hard"]
          : ["hard", "medium", "easy"];
    const next = preference.find((item) => counts[item] > 0) ?? "easy";
    result.push(next);
    counts[next] -= 1;
  }
  return result;
}

function orderedTypes(total: number): QuizQuestionType[] {
  const counts = allocateByRatio(total, TYPE_RATIOS);
  return QUIZ_TYPE_ORDER.flatMap((type) =>
    Array.from({ length: counts[type] }, () => type),
  );
}

function orderedDifficultiesByType(
  types: QuizQuestionType[],
): AssessmentDifficulty[] {
  return QUIZ_TYPE_ORDER.flatMap((type) => {
    const count = types.filter((item) => item === type).length;
    return orderedDifficulties(count);
  });
}

function pointsFor(type: QuizQuestionType, difficulty: AssessmentDifficulty): number {
  if (type === "single_choice" || type === "true_false") {
    return difficulty === "hard" ? 2 : difficulty === "medium" ? 1.5 : 1;
  }
  return difficulty === "hard" ? 12 : difficulty === "medium" ? 10 : 7;
}

export function normalizeQuizCount(value: unknown): number {
  const parsed = Math.trunc(Number(value));
  if (!Number.isFinite(parsed)) return DEFAULT_QUIZ_QUESTION_COUNT;
  return Math.max(MIN_QUIZ_QUESTION_COUNT, Math.min(MAX_QUIZ_QUESTION_COUNT, parsed));
}

export function createQuizBlueprint(
  requestedCount: unknown,
  scores: ScoreMap,
): QuizBlueprintItem[] {
  const total = normalizeQuizCount(requestedCount);
  const dimensions = expandAllocation(allocateDimensions(total, scores));
  const types = orderedTypes(total);
  // Keep each type section internally progressive so grouping the paper does
  // not accidentally make all objective items easy and all subjective items hard.
  const difficulties = orderedDifficultiesByType(types);
  const dimensionCycle = dimensionOrder(scores);
  // Rotate the expanded dimension list so adjacent questions do not repeatedly
  // test the same capability area.
  const orderedDimensions = Array.from({ length: total }, (_, index) => {
    const preferred = dimensionCycle[index % dimensionCycle.length];
    const found = dimensions.indexOf(preferred);
    return found >= 0 ? dimensions.splice(found, 1)[0] : dimensions.shift()!;
  });
  return Array.from({ length: total }, (_, index) => ({
    sequence: index + 1,
    questionType: types[index],
    difficulty: difficulties[index],
    capabilityDimension: orderedDimensions[index],
    points: pointsFor(types[index], difficulties[index]),
  }));
}

export function summarizeQuizBlueprint(
  blueprint: QuizBlueprintItem[],
): QuizBlueprintSummary {
  const byType = Object.fromEntries(
    (Object.keys(TYPE_RATIOS) as QuizQuestionType[]).map((key) => [key, 0]),
  ) as Record<QuizQuestionType, number>;
  const byDifficulty = Object.fromEntries(
    (Object.keys(DIFFICULTY_RATIOS) as AssessmentDifficulty[]).map((key) => [key, 0]),
  ) as Record<AssessmentDifficulty, number>;
  const byDimension = Object.fromEntries(
    CAPABILITY_DIMENSIONS.map((item) => [item.id, 0]),
  ) as Record<CapabilityDimensionId, number>;
  for (const item of blueprint) {
    byType[item.questionType] += 1;
    byDifficulty[item.difficulty] += 1;
    byDimension[item.capabilityDimension] += 1;
  }
  return {
    total: blueprint.length,
    byType,
    byDifficulty,
    byDimension,
    totalPoints: blueprint.reduce((sum, item) => sum + item.points, 0),
  };
}

export function batchQuizBlueprint(
  blueprint: QuizBlueprintItem[],
  batchSize = QUIZ_GENERATION_BATCH_SIZE,
): QuizBlueprintItem[][] {
  const result: QuizBlueprintItem[][] = [];
  for (let index = 0; index < blueprint.length; index += batchSize) {
    result.push(blueprint.slice(index, index + batchSize));
  }
  return result;
}
