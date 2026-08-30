"use client";

import { useCallback, useEffect, useState } from "react";
import {
  loadProfileMarkdown,
  ProfileMarkdownRequestError,
  saveProfileMarkdown,
  type ProfileMarkdownSnapshot,
} from "@/lib/profile-markdown-client";

export default function ProfileMarkdownEditor({ userId }: { userId: string }) {
  const [snapshot, setSnapshot] = useState<ProfileMarkdownSnapshot | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const loaded = await loadProfileMarkdown(userId);
      setSnapshot(loaded);
      setDraft(loaded.editableContent);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "profile.md 读取失败");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    let cancelled = false;
    loadProfileMarkdown(userId)
      .then((loaded) => {
        if (cancelled) return;
        setSnapshot(loaded);
        setDraft(loaded.editableContent);
      })
      .catch((caught) => {
        if (cancelled) return;
        setError(caught instanceof Error ? caught.message : "profile.md 读取失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const changed = snapshot !== null && draft !== snapshot.editableContent;

  async function save() {
    if (!snapshot || !changed || saving) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const saved = await saveProfileMarkdown(userId, draft, snapshot.contentHash);
      setSnapshot(saved);
      setDraft(saved.editableContent);
      setMessage("已保存，新的个性化指令将用于后续 Agent 任务。");
    } catch (caught) {
      if (caught instanceof ProfileMarkdownRequestError && caught.status === 409) {
        setError("profile.md 已被 Agent 更新。请重新加载并确认最新内容后再保存。");
      } else {
        setError(caught instanceof Error ? caught.message : "profile.md 保存失败");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="profile-markdown-editor" aria-labelledby="profile-markdown-title">
      <header className="profile-markdown-heading">
        <div>
          <span className="eyebrow">PROFILE.MD</span>
          <h3 id="profile-markdown-title">自定义指令</h3>
          <p>直接编辑学习背景、学习偏好和教师备注。能力、知识漏洞与学习路径由系统维护。</p>
        </div>
        <div className="profile-markdown-actions">
          <button type="button" className="quiet-button" disabled={loading || saving} onClick={() => void reload()}>
            重新加载
          </button>
          <button type="button" className="primary-button" disabled={!changed || loading || saving} onClick={() => void save()}>
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </header>

      {loading && !snapshot ? (
        <div className="profile-markdown-state" role="status">正在读取当前用户的 profile.md…</div>
      ) : error && !snapshot ? (
        <div className="profile-markdown-state error" role="alert">
          <strong>profile.md 暂时无法读取</strong>
          <span>{error}</span>
          <button type="button" onClick={() => void reload()}>重试</button>
        </div>
      ) : snapshot ? (
        <>
          <div className="profile-markdown-workspace">
            <label className="profile-markdown-editable">
              <span>可编辑内容</span>
              <textarea
                value={draft}
                spellCheck={false}
                aria-describedby="profile-markdown-help"
                onChange={(event) => {
                  setDraft(event.target.value);
                  setMessage("");
                  setError("");
                }}
              />
              <small id="profile-markdown-help">
                保留三个二级标题；保存时不会覆盖其他系统 section。
              </small>
            </label>

            <section className="profile-markdown-readonly" aria-labelledby="profile-markdown-full-title">
              <div>
                <span id="profile-markdown-full-title">profile.md 完整内容</span>
                <small>只读 · 保存后自动刷新</small>
              </div>
              <pre>{snapshot.content}</pre>
            </section>
          </div>

          <div className="profile-markdown-status" aria-live="polite">
            <span className={changed ? "changed" : "saved"}>
              {changed ? "有未保存的修改" : "内容已同步"}
            </span>
            <code title={snapshot.profileMdRef}>{snapshot.profileMdRef}</code>
          </div>
          {message && <p className="profile-markdown-message success">{message}</p>}
          {error && <p className="profile-markdown-message error" role="alert">{error}</p>}
        </>
      ) : null}
    </section>
  );
}
