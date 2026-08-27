# 强制学情摸底设计稿

## 背景

当前工程已经有一条完整的主对话链路：前端提交请求后，后端进入 LangGraph 图，完成输入理解、RAG 检索、内容生成、个性化写入与归档。

仓库里也已经存在摸底相关雏形：
- `agent/onboarding.py`
- `agent/onboarding_api.py`
- `ProfileManager.assign_learning_path()`
- `user_course_path_assignments` SQLite 表
- `web/runtime/doc/users/<user_id>/profile/profile.md`

本设计要把这套雏形变成一个**强制性的首登摸底机制**。

## 目标

- 用户第一次进入系统时，必须先完成摸底。
- 摸底题目必须和知识库源文件相关。
- 摸底结果必须可确定性评分，不依赖 LLM 判卷。
- 分数要映射成三档：低、中、高。
- 分档结果要写入 SQLite、`profile.md`，并驱动后续学习路径。
- 未完成摸底的用户不能进入主对话。

## 非目标

- 不做主观题自动评分。
- 不做自适应出题。
- 不做多课程通用摸底，第一期只覆盖 `cnc_lathe`。
- 不把摸底做成运行时动态生成题库，第一期使用固定版本题库。

## 现状流程

现在主对话流程是：

1. 前端发起 `/api/agent`
2. 后端创建 `run_id`
3. 事件流进入 LangGraph
4. `input_router` 决定走资料生成、QA、反馈或进度链路
5. 结果写入画像、归档和本地存储

摸底能力的现有入口是：

1. `POST /api/onboarding/assessments`
2. `POST /api/onboarding/assessments/{assessment_id}/submit`
3. `POST /api/users`

这说明代码已经有“先测评、再注册、再进入主流程”的基础，只差把它变成强制门禁。

## 方案概述

### 1. 强制门禁

用户进入系统后，前端先检查该用户是否已经有 `cnc_lathe` 的路径分配。

- 有分配：进入主界面
- 没有分配：强制进入摸底页，不能跳过

后端也要同步加门禁：

- 如果 `/api/agent` 收到的是未完成摸底的用户，直接拒绝
- 返回明确错误，例如 `onboarding_required`

这样可以避免前端被绕过。

### 2. 固定题库

第一版使用固定题库，不在线生成。

题库规模建议：

- 10 题
- 全部单选题
- 每题 1 个正确答案
- 每题 1 分，满分 10 分，再换算成 100 分制

题目来源必须来自知识库源文件：

- 安全规程 / 上岗前检查清单
- 机床操作文档 / 操作系统说明书
- 编程说明书 / 编程示例
- 理论课 PPT / 职业技能等级标准
- 安全操作题库 / 考核大纲

题目分布建议：

| 维度 | 题数 | 主要来源 |
| --- | --- | --- |
| 安全 | 2 | 安全规程、检查清单、题库 |
| 基础认知 | 2 | 理论课 PPT、职业标准 |
| 编程基础 | 2 | 编程说明书、编程示例 |
| 操作流程 | 2 | 操作系统说明书、机床操作文档 |
| 质量检测 | 2 | 题库、考核大纲 |

题目要求：

- 一题只考一个知识点
- 题干短，避免歧义
- 干扰项要合理，不能一眼排除
- 不考题外常识
- 不出开放题

## 评分与分档

### 分数

- 每题答对得 1 分
- 总分换算为 100 分制
- `overall_score = round(100 * earned / possible)`

### 分档

- `0 - 49`：低
- `50 - 79`：中
- `80 - 100`：高

### 内部兼容

为了尽量少改现有路径分配逻辑，内部枚举可以继续沿用：

- 低 -> `beginner`
- 中 -> `standard`
- 高 -> `advanced`

对外显示时使用中文档位。

## 持久化设计

摸底完成后，结果必须写入以下位置：

### 1. SQLite

写入 `user_course_path_assignments`：

- `user_id`
- `course_id`
- `learner_level`
- `path_id`
- `path_version`
- `classification_source`
- `classification_score`
- `classification_reason`
- `manual_override`

这里会成为“是否已完成摸底”的权威判断来源。

### 2. `profile.md`

写入：

`web/runtime/doc/users/<user_id>/profile/profile.md`

写入内容建议新增一个“学习路径分配”或“初始化测评结果”章节，记录：

- 总分
- 档位
- 分类原因
- 关键薄弱项

### 3. `path_assignments.json`

同步写入：

`web/runtime/doc/users/<user_id>/profile/path_assignments.json`

用于前端展示和路径读取。

### 4. 能力证据与学情补丁

摸底结果还应继续走现有画像更新链路，把：

- 能力证据
- 知识缺口
- 学习进度初始状态

写入现有画像体系。

## API 交互

建议保留并使用现有三步：

1. `POST /api/onboarding/assessments`
2. `POST /api/onboarding/assessments/{assessment_id}/submit`
3. `POST /api/users`

推荐前端流程：

1. 检查用户是否已有路径分配
2. 没有则创建摸底
3. 用户作答
4. 提交并拿到分数和档位
5. 注册用户并写入画像
6. 放行主对话

## 错误处理

- 缺少答案列表：返回 400
- assessment 不存在：返回 404
- 用户未通过摸底却想进主对话：返回 409 或等价的 `onboarding_required`
- 画像写入失败：返回 500

## 验收标准

- 新用户第一次进入时只能看到摸底
- 完成摸底后，系统生成分数与低/中/高档位
- SQLite 中出现 `user_course_path_assignments` 记录
- `profile.md` 被更新
- `path_assignments.json` 被更新
- 未完成摸底的用户无法直接进入 `/api/agent`

## 实施建议

第一期只做 `cnc_lathe`，先把流程跑通。

如果后续要扩展到别的课程，再把题库与路径分配拆成课程级配置即可，不需要重写整套门禁。
