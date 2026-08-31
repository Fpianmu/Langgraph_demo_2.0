export type LearningPathAssignment = {
  user_id: string;
  course_id: string;
  learner_level?: string;
  path_id: string;
  path_version?: string;
  classification_source?: string;
  classification_score?: number;
  classification_reason?: string;
  manual_override?: boolean;
  assigned_at?: string;
  updated_at?: string;
};

export type BackendChapterProgress = {
  progress_id?: string;
  course_id: string;
  path_id?: string;
  path_version?: string;
  chapter_id: string;
  chapter_order?: number;
  status?: string;
  completion_rate?: number;
  last_activity_at?: string;
  updated_at?: string;
};

export type LearningPathChapter = {
  chapter_id: string;
  chapter_title: string;
  chapter_order: number;
  next_chapter_id?: string | null;
  required?: boolean;
  required_material_types: string[];
  focus: {
    summary: string;
    required_material_types: string[];
    focus_items: Array<Record<string, unknown>>;
  };
};

export type UserLearningPath = {
  course_id: string;
  course_title: string;
  path_id: string;
  path_title: string;
  profile_level: string;
  default_chapter_id: string;
  generation_policy: Record<string, unknown>;
  chapters: LearningPathChapter[];
  assignment: LearningPathAssignment | null;
  progress: BackendChapterProgress[];
  current_chapter_id: string;
};

type ErrorPayload = { error?: string; detail?: string };

async function requestJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  const payload = (await response.json().catch(() => ({}))) as T & ErrorPayload;
  if (!response.ok) {
    throw new Error(
      payload.detail || payload.error || `学习路径接口返回 HTTP ${response.status}`,
    );
  }
  return payload;
}

function updatedTimestamp(item: BackendChapterProgress): number {
  const value = item.updated_at || item.last_activity_at || "";
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function selectCurrentChapter(
  chapters: LearningPathChapter[],
  progress: BackendChapterProgress[],
  defaultChapterId: string,
): string {
  const validIds = new Set(chapters.map((chapter) => chapter.chapter_id));
  const relevant = progress.filter((item) => validIds.has(item.chapter_id));
  const active = relevant
    .filter((item) =>
      ["in_progress", "needs_review", "learning"].includes(
        String(item.status || "").toLowerCase(),
      ),
    )
    .sort((left, right) => updatedTimestamp(right) - updatedTimestamp(left));
  if (active[0]) return active[0].chapter_id;
  const latest = [...relevant].sort(
    (left, right) => updatedTimestamp(right) - updatedTimestamp(left),
  )[0];
  return latest?.chapter_id || defaultChapterId || chapters[0]?.chapter_id || "";
}

export async function loadUserLearningPath(
  userId: string,
  courseId = "cnc_lathe",
): Promise<UserLearningPath> {
  const assignmentPayload = await requestJson<{
    path_assignments?: LearningPathAssignment[];
  }>(
    `/api/storage/users/${encodeURIComponent(userId)}/path-assignments`,
  );
  const assignments = Array.isArray(assignmentPayload.path_assignments)
    ? assignmentPayload.path_assignments
    : [];
  const assignment =
    assignments.find((item) => item.course_id === courseId) || assignments[0] || null;
  const pathId = assignment?.path_id || "standard";

  const [pathPayload, progressPayload] = await Promise.all([
    requestJson<{
      course_id?: string;
      course_title?: string;
      default_chapter_id?: string;
      path_id?: string;
      path_title?: string;
      profile_level?: string;
      generation_policy?: Record<string, unknown>;
      chapters?: LearningPathChapter[];
    }>(
      `/api/courses/${encodeURIComponent(courseId)}/learning-path?path_id=${encodeURIComponent(pathId)}`,
    ),
    requestJson<{ learning_progress?: BackendChapterProgress[] }>(
      `/api/storage/users/${encodeURIComponent(userId)}/learning-progress`,
    ),
  ]);

  const chapters = (Array.isArray(pathPayload.chapters) ? pathPayload.chapters : [])
    .filter((chapter) => chapter && typeof chapter.chapter_id === "string")
    .map((chapter) => ({
      ...chapter,
      chapter_title: chapter.chapter_title || chapter.chapter_id,
      chapter_order: Number(chapter.chapter_order || 0),
      required_material_types: Array.isArray(chapter.required_material_types)
        ? chapter.required_material_types
        : Array.isArray(chapter.focus?.required_material_types)
          ? chapter.focus.required_material_types
          : [],
      focus: {
        summary: chapter.focus?.summary || chapter.chapter_title || chapter.chapter_id,
        required_material_types: Array.isArray(chapter.focus?.required_material_types)
          ? chapter.focus.required_material_types
          : [],
        focus_items: Array.isArray(chapter.focus?.focus_items)
          ? chapter.focus.focus_items
          : [],
      },
    }))
    .sort((left, right) => left.chapter_order - right.chapter_order);
  if (!chapters.length) throw new Error("后端学习路径没有返回章节目录");

  const progress = (Array.isArray(progressPayload.learning_progress)
    ? progressPayload.learning_progress
    : []
  ).filter(
    (item) =>
      item.course_id === courseId && (!item.path_id || item.path_id === pathId),
  );
  const defaultChapterId = pathPayload.default_chapter_id || chapters[0].chapter_id;

  return {
    course_id: pathPayload.course_id || courseId,
    course_title: pathPayload.course_title || "数控车床",
    path_id: pathPayload.path_id || pathId,
    path_title: pathPayload.path_title || assignment?.classification_reason || pathId,
    profile_level: pathPayload.profile_level || assignment?.learner_level || pathId,
    default_chapter_id: defaultChapterId,
    generation_policy: pathPayload.generation_policy || {},
    chapters,
    assignment,
    progress,
    current_chapter_id: selectCurrentChapter(chapters, progress, defaultChapterId),
  };
}
