# Quiz 会话、断点续答与历史记录

版本：`zlink-quiz-session-v2`

## 生成蓝图

默认生成 50 题，自定义范围为 8～50 题。系统先生成确定性蓝图，再以 10 题一批交给中央调度器和 RAG，避免一次输出 50 题造成截断。默认训练卷采用：

- 单项选择 44%、判断 16%、知识点填空 20%、简答 20%；
- 基础 30%、中等 50%、进阶 20%；
- 八个能力维度至少各有一道题，剩余题量优先分配给低分维度；
- 客观题按难度计 1/1.5/2 分，填空和简答按难度计 7/10/12 分。

该结构是知链的岗位训练规则，不冒充职业技能等级考试的官方试卷结构。50 题的最终分数使用 `earned / possible` 计算，可自然适配自定义题量。

## 保存时机

1. 中央调度器成功返回题目后，立即创建 Quiz 会话并保存题目快照。
2. 用户选择选项时保存草稿答案，不计入能力分数。
3. 用户提交答案时保存得分、评分方法、正确性和提交时间，并立即生成一条能力证据。
4. 用户切换题号时保存当前题号。
5. 全部题目提交后将会话标记为 `completed`，记录完成时间并向反馈 Agent 发送结构化结果。

因此刷新页面、切换功能或者重新打开知链后，都可以恢复最后一道题和未提交的选项。

## 会话数据

每条 `QuizSession` 保存：

- 会话 ID、中央调度器 request ID、课程和章节；
- 主题、考查重点、难度、创建/更新时间；
- 完整题目、题型、分值、答案、评分量规以及简洁/详细解析快照；
- 当前题号、长文本草稿、已提交答案、部分得分、语义相似度、评分点覆盖和提交时间；
- `in_progress`、`completed` 或 `abandoned` 状态；
- RAG 查询、文档来源、chunk ID、置信度和知识库版本。

只保存分数或题目 ID 无法稳定回顾历史，因此题目内容必须随会话保存。

## 持久化

Quiz 会话随完整工作区写入：

```text
frontend_state.quiz_sessions
frontend_state.active_quiz_session_id
```

后端 SQLite 中的 `frontend_state.state_json` 是正式存储，浏览器 `localStorage` 是后端不可用时的恢复缓存。最多保留最近 50 次会话，避免浏览器缓存无限增长。

连接尚未支持这些字段的旧版后端时，前端会自动使用旧协议重试，Quiz 会话仍保留在本地缓存；后端加入可选字段后会自动开始同步。

## 能力评分去重

每条能力证据使用稳定的题目 ID：

```text
quiz-session-id + question-index
```

只有提交后的答案生成证据。草稿、历史查看、刷新恢复或反复打开同一结果不会重复计分。即使整套 Quiz 尚未完成，已经提交的题目也会参与能力评估。

## RAG 兼容

中央调度器可以在题目或 `rag_package` 中返回：

```json
{
  "capability_dimension": "programming",
  "knowledge_point": "G71 外圆粗车循环",
  "source_refs": ["数控车编程与操作.pdf"],
  "rag_chunk_ids": ["chapter-3-chunk-17"],
  "question_type": "short_answer",
  "points": 10,
  "scoring_rubric": {
    "key_points": [
      {"id": "kp1", "description": "说明程序校验目的", "points": 4}
    ]
  }
}
```

知链会把这些字段复制进题目快照和 Quiz 检索上下文。历史回顾读取当时保存的来源，不会重新检索后用新内容冒充原始依据。知识库以后增加版本号时，可以通过 `final_output.meta.knowledge_base_version` 或 `corpus_version` 一起归档。

## 主观题评分

填空和简答通过独立的 `/agent/quiz/grade` 接口评分。配置 `QUIZ_EMBEDDING_API_URL`、`QUIZ_EMBEDDING_API_KEY` 和 `QUIZ_EMBEDDING_MODEL` 后，采用神经语义向量、关键评分点、事实判断、否定/矛盾检测和安全红线的组合分数。未配置神经 Embedding 时会明确标记为 `agent_semantic_rubric_local_vector`，主要依赖中央评分 Agent，本地字符向量只占低权重，不会伪装成神经语义评分。

出现逻辑矛盾时得分封顶 50%；出现严重安全错误时得分封顶 40%。每次评分保存模型方法、语义相似度、评分点命中和反馈，因此 Memory 能解释分数来源。

## 后续数据库拆分

当前 50 条以内的简易版本使用 `frontend_state` 已足够。如果以后需要教师端统计、大规模题库分析或多用户查询，可以将相同结构拆分为：

```text
quiz_sessions
quiz_questions
quiz_answers
quiz_rag_sources
```

前端会话 ID 和题目 ID 可以直接作为迁移主键，能力证据不需要重新生成。
