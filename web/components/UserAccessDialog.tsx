"use client";

import { useEffect, useMemo, useState } from "react";
import {
  createOnboardingAssessment,
  createRegisteredUser,
  submitOnboardingAssessment,
  type OnboardingAssessment,
  type OnboardingResult,
  type UserSummary,
} from "@/lib/user-client";

type DialogMode = "switch" | "create" | null;

const LEVEL_LABELS: Record<string, string> = {
  beginner: "基础路径",
  standard: "标准路径",
  advanced: "进阶路径",
};

const DIMENSION_LABELS: Record<string, string> = {
  foundations: "专业基础",
  safety: "安全规范",
  programming: "数控编程",
  machining_operation: "操作加工",
  quality_control: "质量检测",
};

function generatedUserId() {
  return `user_${Date.now().toString(36)}`;
}

export function UserAccessDialog({
  mode,
  users,
  activeUserId,
  onClose,
  onModeChange,
  onSelect,
  onCreated,
}: {
  mode: DialogMode;
  users: UserSummary[];
  activeUserId: string;
  onClose: () => void;
  onModeChange: (mode: Exclude<DialogMode, null>) => void;
  onSelect: (user: UserSummary) => void;
  onCreated: (user: UserSummary) => void;
}) {
  const [displayName, setDisplayName] = useState("");
  const [userId, setUserId] = useState(generatedUserId);
  const [backgroundType, setBackgroundType] = useState("零基础学习者");
  const [assessment, setAssessment] = useState<OnboardingAssessment | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [questionIndex, setQuestionIndex] = useState(0);
  const [result, setResult] = useState<OnboardingResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!mode) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onClose();
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [busy, mode, onClose]);

  const currentQuestion = assessment?.questions[questionIndex];
  const answeredCount = useMemo(
    () => Object.values(answers).filter(Boolean).length,
    [answers],
  );

  if (!mode) return null;

  async function startAssessment() {
    if (!displayName.trim()) {
      setError("请输入学习者名称");
      return;
    }
    if (!/^[a-zA-Z0-9_-]{3,48}$/.test(userId.trim())) {
      setError("用户 ID 需为 3–48 位字母、数字、下划线或短横线");
      return;
    }
    if (users.some((user) => user.user_id === userId.trim())) {
      setError("该用户 ID 已存在，请更换一个");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const next = await createOnboardingAssessment("cnc_lathe");
      setAssessment(next);
      setQuestionIndex(0);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "入门测评创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function submitAssessment() {
    if (!assessment) return;
    if (answeredCount !== assessment.questions.length) {
      setError("请完成全部题目后再提交测评");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const scored = await submitOnboardingAssessment(
        assessment.assessment_id,
        assessment.questions.map((question) => ({
          question_id: question.id,
          answer: answers[question.id],
        })),
      );
      if (scored.status !== "scored") throw new Error("后端未返回有效评分结果");
      setResult(scored);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "测评提交失败");
    } finally {
      setBusy(false);
    }
  }

  async function finishRegistration() {
    if (!result) return;
    setBusy(true);
    setError("");
    try {
      await createRegisteredUser({
        user_id: userId.trim(),
        display_name: displayName.trim(),
        background_type: backgroundType,
        assessment_result: result,
      });
      onCreated({
        user_id: userId.trim(),
        display_name: displayName.trim(),
        background_type: backgroundType,
      });
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "用户创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="user-access-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <section className="user-access-dialog" role="dialog" aria-modal="true">
        <header className="user-access-header">
          <div>
            <p>{mode === "switch" ? "LEARNER ACCOUNT" : "ONBOARDING"}</p>
            <h2>{mode === "switch" ? "切换学习者" : "创建新学习者"}</h2>
            <span>
              {mode === "switch"
                ? "每位学习者的问答、测验、讲义和画像相互独立。"
                : "完成基础信息和入门测评后，知链才会建立正式用户。"}
            </span>
          </div>
          <button type="button" aria-label="关闭" onClick={onClose} disabled={busy}>×</button>
        </header>

        {mode === "switch" ? (
          <div className="user-switch-content">
            <div className="user-switch-list">
              {users.length ? users.map((user) => (
                <button
                  type="button"
                  key={user.user_id}
                  className={user.user_id === activeUserId ? "active" : ""}
                  onClick={() => onSelect(user)}
                >
                  <span className="user-switch-avatar">
                    {(user.display_name || user.user_id).trim().slice(0, 1).toUpperCase()}
                  </span>
                  <span>
                    <strong>{user.display_name || user.user_id}</strong>
                    <small>{user.background_type || user.user_id}</small>
                  </span>
                  <em>{user.user_id === activeUserId ? "当前" : "切换"}</em>
                </button>
              )) : (
                <p className="user-list-empty">后端尚未登记学习者，请先创建新用户。</p>
              )}
            </div>
            <button type="button" className="user-access-primary" onClick={() => onModeChange("create")}>
              ＋ 创建新学习者
            </button>
          </div>
        ) : !assessment ? (
          <div className="onboarding-profile-step">
            <div className="onboarding-steps"><b>1</b><span>基础信息</span><i /><b>2</b><span>入门测评</span><i /><b>3</b><span>建立画像</span></div>
            <label>
              <span>学习者名称</span>
              <input value={displayName} maxLength={20} onChange={(event) => setDisplayName(event.target.value)} placeholder="例如：陈同学" autoFocus />
            </label>
            <div className="onboarding-field-grid">
              <label>
                <span>用户 ID</span>
                <input value={userId} onChange={(event) => setUserId(event.target.value)} />
                <small>仅用于区分本机数据，创建后不可更改</small>
              </label>
              <label>
                <span>学习背景</span>
                <select value={backgroundType} onChange={(event) => setBackgroundType(event.target.value)}>
                  <option value="零基础学习者">零基础学习者</option>
                  <option value="机械相关专业">机械相关专业</option>
                  <option value="非机械专业">非机械专业</option>
                  <option value="一线操作人员">一线操作人员</option>
                  <option value="职业院校学生">职业院校学生</option>
                </select>
              </label>
            </div>
            <div className="onboarding-note">入门测评用于生成初始能力证据、知识漏洞和学习路径，不是可跳过的装饰步骤。</div>
            {error && <p className="user-access-error">{error}</p>}
            <div className="user-access-actions">
              <button type="button" onClick={() => onModeChange("switch")}>返回用户列表</button>
              <button type="button" className="primary" onClick={startAssessment} disabled={busy}>{busy ? "正在创建…" : "开始入门测评"}</button>
            </div>
          </div>
        ) : !result && currentQuestion ? (
          <div className="onboarding-assessment-step">
            <div className="onboarding-progress-row">
              <span>入门测评 · {questionIndex + 1}/{assessment.questions.length}</span>
              <strong>{Math.round((answeredCount / assessment.questions.length) * 100)}%</strong>
            </div>
            <div className="onboarding-progress-track"><span style={{ width: `${(answeredCount / assessment.questions.length) * 100}%` }} /></div>
            <p className="onboarding-question-meta">{DIMENSION_LABELS[currentQuestion.capability_dimension] || currentQuestion.capability_dimension} · {currentQuestion.difficulty === "easy" ? "基础" : "进阶"}</p>
            <h3>{currentQuestion.stem}</h3>
            <div className="onboarding-options">
              {currentQuestion.options.map((option, index) => {
                const key = String.fromCharCode(65 + index);
                return (
                  <button
                    type="button"
                    key={key}
                    className={answers[currentQuestion.id] === key ? "selected" : ""}
                    onClick={() => setAnswers((current) => ({ ...current, [currentQuestion.id]: key }))}
                  >
                    <b>{key}</b><span>{option}</span>
                  </button>
                );
              })}
            </div>
            {error && <p className="user-access-error">{error}</p>}
            <div className="user-access-actions">
              <button type="button" disabled={questionIndex === 0 || busy} onClick={() => setQuestionIndex((index) => index - 1)}>上一题</button>
              {questionIndex < assessment.questions.length - 1 ? (
                <button type="button" className="primary" disabled={!answers[currentQuestion.id]} onClick={() => setQuestionIndex((index) => index + 1)}>下一题</button>
              ) : (
                <button type="button" className="primary" disabled={busy || answeredCount !== assessment.questions.length} onClick={submitAssessment}>{busy ? "正在评分…" : "提交测评"}</button>
              )}
            </div>
          </div>
        ) : result ? (
          <div className="onboarding-result-step">
            <div className="onboarding-result-score"><strong>{result.overall_score}</strong><span>入门测评得分</span></div>
            <div>
              <p className="onboarding-result-kicker">测评已由第二版后端完成评分</p>
              <h3>建议进入「{LEVEL_LABELS[result.learner_level] || result.learner_level}」</h3>
              <p>创建用户后，能力证据、初始知识漏洞和学习路径会一起写入该用户的独立存储。</p>
            </div>
            <div className="onboarding-dimension-grid">
              {Object.entries(result.dimension_scores).map(([dimension, score]) => (
                <span key={dimension}><small>{DIMENSION_LABELS[dimension] || dimension}</small><strong>{score} 分</strong></span>
              ))}
            </div>
            {error && <p className="user-access-error">{error}</p>}
            <div className="user-access-actions">
              <button type="button" onClick={() => { setAssessment(null); setResult(null); }}>重新填写</button>
              <button type="button" className="primary" onClick={finishRegistration} disabled={busy}>{busy ? "正在建立画像…" : "创建用户并进入知链"}</button>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
