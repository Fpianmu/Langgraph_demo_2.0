from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.storage_layout import resolve_storage_root, safe_segment, user_root
from agent.tools.profile_tools import load_profile_context


CAPABILITY_LABELS = {
    "safety": "安全规范",
    "foundations": "基础识图",
    "process_planning": "工艺规划",
    "programming": "数控编程",
    "machining_operation": "操作加工",
    "quality_control": "质量检测",
    "maintenance": "维护诊断",
    "advanced_manufacturing": "先进制造",
}


CNC_TRACKS: list[dict[str, Any]] = [
    {
        "id": "safety",
        "title": "数控机床安全操作",
        "capability_dimension": "safety",
        "keywords": ["安全", "急停", "防护", "事故", "风险", "违规", "操作规程", "开机检查", "防护门"],
        "topic": "数控机床安全操作",
        "focus": "开机前检查、个人防护、急停操作、异常报警与规范处置",
        "default_priority": 1.2,
    },
    {
        "id": "operation",
        "title": "数控车铣基本操作",
        "capability_dimension": "machining_operation",
        "keywords": ["操作", "装夹", "对刀", "刀具", "首件", "试切", "机床", "车削", "铣削", "回零"],
        "topic": "数控车铣加工基本操作",
        "focus": "工件装夹、刀具安装、对刀、程序校验、空运行与首件试切",
        "default_priority": 1.1,
    },
    {
        "id": "theory",
        "title": "数控加工基础理论",
        "capability_dimension": "foundations",
        "keywords": ["理论", "坐标系", "切削参数", "刀具补偿", "工艺", "公差", "测量", "基础知识", "识图"],
        "topic": "数控加工基础理论",
        "focus": "机床坐标系、工件坐标系、刀具补偿、切削参数与尺寸精度",
        "default_priority": 1.0,
    },
    {
        "id": "programming",
        "title": "数控编程与程序校验",
        "capability_dimension": "programming",
        "keywords": ["编程", "程序", "g代码", "m代码", "g-code", "m-code", "循环指令", "仿真", "程序校验", "刀补"],
        "topic": "数控加工程序编制与校验",
        "focus": "程序结构、G/M 指令、刀具补偿、循环指令与程序校验",
        "default_priority": 0.9,
    },
    {
        "id": "multiaxis",
        "title": "多轴数控加工",
        "capability_dimension": "advanced_manufacturing",
        "keywords": ["多轴", "五轴", "四轴", "联动", "旋转轴", "刀轴", "后处理", "碰撞"],
        "topic": "多轴数控加工基础",
        "focus": "旋转轴定义、坐标变换、联动加工、后处理与碰撞检查",
        "default_priority": 0.8,
    },
    {
        "id": "certificate",
        "title": "职业技能等级考核",
        "capability_dimension": "process_planning",
        "keywords": ["证书", "考核", "考试", "职业标准", "初级", "中级", "高级", "题库", "复习"],
        "topic": "数控车铣加工职业技能等级考核",
        "focus": "安全规范、基础理论、程序编制、操作流程与质量检测",
        "default_priority": 0.7,
    },
]


def build_learning_recommendations(profile_context: dict[str, Any]) -> dict[str, Any]:
    user_id = str(profile_context.get("user_id") or "default_user")
    scores = _score_map(profile_context)
    profile_text = _profile_text(profile_context)
    memory_text = _memory_text(profile_context)
    now = _utc_now()
    ranked = []
    for index, track in enumerate(CNC_TRACKS):
        dimension = str(track["capability_dimension"])
        score = _clamp_score(scores.get(dimension))
        memory_hits = _keyword_hits(f"{profile_text} {memory_text}", track["keywords"])
        gap = 100 - score
        rank = float(track["default_priority"]) + gap / 18 + memory_hits * 3.5 - index * 0.001
        ranked.append(
            {
                "track": track,
                "rank": round(rank, 4),
                "score": score,
                "memory_hits": memory_hits,
                "matched_keywords": _matched_keywords(f"{profile_text} {memory_text}", track["keywords"]),
            }
        )
    ranked.sort(key=lambda item: item["rank"], reverse=True)
    recommendations = [_recommendation_item(item) for item in ranked[:6]]
    origin = "memory" if any(item["memory_hits"] > 0 for item in ranked) else "profile"
    first = recommendations[0] if recommendations else {}
    return {
        "status": "success",
        "user_id": user_id,
        "updated_at": now,
        "origin": origin,
        "primary_topic": str(first.get("topic") or ""),
        "context_label": _context_label(first, origin),
        "recommendations": recommendations,
        "trace": {
            "source": "profile_context",
            "ranked_tracks": [
                {
                    "id": item["track"]["id"],
                    "rank": item["rank"],
                    "capability_dimension": item["track"]["capability_dimension"],
                    "score": item["score"],
                    "memory_hits": item["memory_hits"],
                    "matched_keywords": item["matched_keywords"],
                }
                for item in ranked
            ],
        },
    }


def refresh_learning_recommendations(
    *,
    user_id: str,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    context = load_profile_context(user_id=user_id, storage_root=storage_root)
    result = build_learning_recommendations(context)
    paths = recommendation_paths(user_id=user_id, storage_root=storage_root)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    paths["json"].write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["markdown"].write_text(_recommendation_markdown(result), encoding="utf-8")
    return {
        **result,
        "files": {
            "json": str(paths["json"]),
            "markdown": str(paths["markdown"]),
        },
    }


def load_learning_recommendations(
    *,
    user_id: str,
    storage_root: str | Path | None = None,
    refresh_if_missing: bool = True,
) -> dict[str, Any]:
    paths = recommendation_paths(user_id=user_id, storage_root=storage_root)
    if not paths["json"].exists():
        if refresh_if_missing:
            return refresh_learning_recommendations(user_id=user_id, storage_root=storage_root)
        return {"status": "missing", "user_id": user_id, "recommendations": []}
    try:
        value = json.loads(paths["json"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        if refresh_if_missing:
            return refresh_learning_recommendations(user_id=user_id, storage_root=storage_root)
        return {"status": "invalid", "user_id": user_id, "recommendations": []}
    if not isinstance(value, dict):
        return {"status": "invalid", "user_id": user_id, "recommendations": []}
    return value


def refresh_due_learning_recommendations(
    *,
    storage_root: str | Path | None = None,
    max_age_seconds: int = 1800,
) -> dict[str, Any]:
    root = resolve_storage_root(storage_root)
    users_dir = root / "users"
    items = []
    if not users_dir.exists():
        return {"status": "success", "refreshed_count": 0, "items": []}
    now = datetime.now(timezone.utc).timestamp()
    for user_dir in users_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        paths = recommendation_paths(user_id=user_id, storage_root=root)
        json_path = paths["json"]
        stale = not json_path.exists()
        if json_path.exists():
            stale = now - json_path.stat().st_mtime >= max(0, int(max_age_seconds))
        if not stale:
            continue
        refreshed = refresh_learning_recommendations(user_id=user_id, storage_root=root)
        items.append(
            {
                "user_id": user_id,
                "status": refreshed.get("status"),
                "updated_at": refreshed.get("updated_at"),
                "primary_topic": refreshed.get("primary_topic"),
            }
        )
    return {"status": "success", "refreshed_count": len(items), "items": items}


def recommendation_quiz_payload(
    *,
    user_id: str,
    recommendation_id: str,
    course_id: str = "cnc_lathe",
    chapter_id: str = "",
    question_count: int = 5,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    cache = load_learning_recommendations(user_id=user_id, storage_root=storage_root)
    recommendation = _find_recommendation(cache, recommendation_id)
    if not recommendation:
        raise KeyError(recommendation_id)
    question_count = min(max(int(question_count or 5), 1), 50)
    slots = [
        {
            "sequence": index + 1,
            "question_type": "single_choice" if index < max(question_count - 1, 1) else "short_answer",
            "question_purpose": "chapter_core",
            "difficulty": "easy" if index < 2 else "normal",
            "points": 1.0 if index < max(question_count - 1, 1) else 7.0,
            "capability_dimension": recommendation["capability_dimension"],
            "related_gap_ids": [],
        }
        for index in range(question_count)
    ]
    prompt = (
        f"请围绕“{recommendation['topic']}”生成练习题，重点考查：{recommendation['focus']}。"
        f"推荐原因：{recommendation['reason']}"
    )
    return {
        "user_id": user_id,
        "course_id": course_id,
        "chapter_id": chapter_id,
        "content_type": "quiz",
        "raw_prompt": prompt,
        "task": prompt,
        "quiz_generation_prompt": prompt,
        "quiz_question_count": question_count,
        "quiz_blueprint_input": {
            "source": "learning_recommendation",
            "recommendation_id": recommendation_id,
            "topic": recommendation["topic"],
            "focus": recommendation["focus"],
            "capability_dimension": recommendation["capability_dimension"],
            "question_count": question_count,
            "core_exam_points": [recommendation["focus"]],
            "knowledge_points": [
                {
                    "id": f"recommendation.{safe_segment(recommendation_id)}",
                    "name": recommendation["topic"],
                    "chapter_id": chapter_id,
                    "weight": 1.0,
                }
            ],
            "slots": slots,
        },
        "_storage_root": str(storage_root) if storage_root is not None else None,
    }


def recommendation_paths(*, user_id: str, storage_root: str | Path | None = None) -> dict[str, Path]:
    root = resolve_storage_root(storage_root)
    directory = user_root(root, user_id) / "profile" / "recommendations"
    return {
        "dir": directory,
        "json": directory / "learning_recommendations.json",
        "markdown": directory / "learning_recommendations.md",
    }


def _recommendation_item(ranked_item: dict[str, Any]) -> dict[str, Any]:
    track = ranked_item["track"]
    dimension = str(track["capability_dimension"])
    score = ranked_item["score"]
    matched = ranked_item["matched_keywords"]
    reason = (
        f"{CAPABILITY_LABELS.get(dimension, dimension)}能力分数为 {round(score)} 分，"
        f"且近期画像/知识漏洞命中：{'、'.join(matched[:5])}。"
        if matched
        else f"{CAPABILITY_LABELS.get(dimension, dimension)}能力分数为 {round(score)} 分。"
    )
    return {
        "id": str(track["id"]),
        "title": str(track["title"]),
        "summary": f"建议优先练习{track['focus']}。",
        "reason": reason,
        "topic": str(track["topic"]),
        "focus": str(track["focus"]),
        "capability_dimension": dimension,
        "origin": "memory" if matched else "profile",
        "score": ranked_item["rank"],
        "matched_keywords": matched,
        "recommended_actions": [
            f"完成 5 道“{track['topic']}”相关练习题。",
            f"复盘错题中与“{track['focus']}”相关的知识点。",
        ],
    }


def _score_map(profile_context: dict[str, Any]) -> dict[str, float]:
    result = {key: 60.0 for key in CAPABILITY_LABELS}
    profile_score = profile_context.get("capability_profile_score") if isinstance(profile_context.get("capability_profile_score"), dict) else {}
    profile_dimensions = profile_score.get("dimensions") if isinstance(profile_score.get("dimensions"), dict) else {}
    for dimension in CAPABILITY_LABELS:
        score = _number(profile_dimensions.get(dimension))
        if score is not None and score > 0:
            result[dimension] = _clamp_score(score)
    assessment = profile_context.get("capability_assessment") if isinstance(profile_context.get("capability_assessment"), dict) else {}
    score_map = assessment.get("score_map") if isinstance(assessment.get("score_map"), dict) else {}
    for dimension in CAPABILITY_LABELS:
        if result[dimension] != 60.0:
            continue
        provisional = score_map.get(f"{dimension}_provisional")
        rated = score_map.get(dimension)
        if _number(rated) and _number(score_map.get(f"{dimension}_assessed")):
            result[dimension] = _clamp_score(rated)
        elif _number(provisional):
            result[dimension] = _clamp_score(provisional)
    return result


def _profile_text(profile_context: dict[str, Any]) -> str:
    parts = [
        profile_context.get("profile_md_content"),
        profile_context.get("user"),
        profile_context.get("path_assignments"),
        profile_context.get("learning_progress"),
    ]
    return _normalize(" ".join(json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item or "") for item in parts))


def _memory_text(profile_context: dict[str, Any]) -> str:
    parts = [
        profile_context.get("knowledge_gaps"),
        profile_context.get("knowledge_gap_summary"),
        profile_context.get("capability_assessment_summary"),
    ]
    return _normalize(" ".join(json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item or "") for item in parts))


def _keyword_hits(text: str, keywords: list[str]) -> int:
    return len(_matched_keywords(text, keywords))


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    normalized_text = _normalize(text)
    result = []
    for keyword in keywords:
        token = _normalize(keyword)
        if token and token in normalized_text:
            result.append(str(keyword))
    return result


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _clamp_score(value: Any) -> float:
    parsed = _number(value)
    if parsed is None:
        return 60.0
    return min(max(parsed, 0.0), 100.0)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _context_label(first: dict[str, Any], origin: str) -> str:
    if not first:
        return "暂无推荐。"
    source = "画像和知识漏洞" if origin == "memory" else "画像能力分数"
    return f"已根据{source}更新推荐，当前优先：{first.get('title')}。"


def _recommendation_markdown(result: dict[str, Any]) -> str:
    recommendations = result.get("recommendations") if isinstance(result.get("recommendations"), list) else []
    first = recommendations[0] if recommendations else {}
    lines = [
        f"# 学习推荐：{result.get('user_id') or ''}",
        "",
        f"更新时间：{result.get('updated_at') or ''}",
        "",
    ]
    if first:
        lines.extend(
            [
                f"当前优先推荐：{first.get('title')}",
                "",
                f"原因：{first.get('reason')}",
                "",
                f"建议练习：{first.get('summary')}",
                "",
            ]
        )
    lines.append("## 推荐列表")
    lines.append("")
    for index, item in enumerate(recommendations, start=1):
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"{index}. {item.get('title')}",
                f"   - 方向：{item.get('topic')}",
                f"   - 重点：{item.get('focus')}",
                f"   - 原因：{item.get('reason')}",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _find_recommendation(cache: dict[str, Any], recommendation_id: str) -> dict[str, Any] | None:
    for item in cache.get("recommendations") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == recommendation_id:
            return item
    return None
