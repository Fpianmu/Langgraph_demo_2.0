from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent.course_resources.config import resolve_course_resource_root
from agent.storage_layout import ensure_within, safe_segment


class CourseResourceRepository:
    def __init__(self, resource_root: str | Path | None = None):
        self.resource_root = resolve_course_resource_root(resource_root)

    def load_course_manifest(self, course_id: str) -> dict[str, Any]:
        course_root = self._course_root(course_id)
        return self._read_json(course_root / "course_manifest.json", course_root)

    def load_learning_path(self, course_id: str, path_id: str) -> dict[str, Any]:
        course_root = self._course_root(course_id)
        course_manifest = self.load_course_manifest(course_id)
        path_index = course_manifest.get("learning_path_index")
        if isinstance(path_index, dict):
            relative_path = path_index.get(path_id)
            if not relative_path:
                raise KeyError(f"learning path {path_id} is not indexed by course {course_id}")
            path = ensure_within(course_root, course_root / str(relative_path))
        else:
            path = course_root / "learning_paths" / safe_segment(path_id) / "path.json"
        return self._read_json(path, course_root)

    def load_chapter_asset_bundle(self, course_id: str, chapter_id: str) -> dict[str, Any]:
        course_root = self._course_root(course_id)
        course_manifest = self.load_course_manifest(course_id)
        chapter_root = self._chapter_root(course_root, course_manifest, chapter_id)
        chapter_manifest = self._read_json(chapter_root / "chapter_manifest.json", course_root)
        assets = self._chapter_assets(chapter_root, chapter_manifest)
        return {
            "course_id": course_manifest.get("course_id") or course_id,
            "chapter_id": chapter_manifest.get("chapter_id") or chapter_id,
            "title": chapter_manifest.get("title") or "",
            "chapter_path": chapter_root.as_posix(),
            "chapter_manifest": chapter_manifest,
            "assets": assets,
        }

    def load_manual_lecture(self, course_id: str, chapter_id: str) -> dict[str, Any]:
        bundle = self.load_chapter_asset_bundle(course_id, chapter_id)
        lecture = bundle.get("assets", {}).get("lecture", {})
        manual = lecture.get("manual_lecture") if isinstance(lecture, dict) else None
        if not isinstance(manual, dict):
            raise KeyError(f"chapter {chapter_id} has no manual lecture")
        return self._read_text_asset(manual)

    def load_reference_quiz(self, course_id: str, chapter_id: str) -> dict[str, Any]:
        bundle = self.load_chapter_asset_bundle(course_id, chapter_id)
        quiz = bundle.get("assets", {}).get("reference_quiz", {})
        questions = quiz.get("questions") if isinstance(quiz, dict) else None
        if not isinstance(questions, dict):
            raise KeyError(f"chapter {chapter_id} has no reference quiz")
        data = self._read_json(Path(questions["path"]), self.resource_root)
        data["path"] = questions["path"]
        return data

    def load_operation_task_bundle(self, course_id: str, chapter_id: str, task_id: str) -> dict[str, Any]:
        bundle = self.load_chapter_asset_bundle(course_id, chapter_id)
        tasks = bundle.get("assets", {}).get("operation_tasks", [])
        if not isinstance(tasks, list):
            raise KeyError(f"chapter {chapter_id} has no operation tasks")
        for task in tasks:
            if isinstance(task, dict) and str(task.get("task_id") or "") == task_id:
                return task
        raise KeyError(f"task {task_id} is not indexed by chapter {chapter_id}")

    def load_workpiece_standard_spec(self, course_id: str, workpiece_id: str) -> dict[str, Any]:
        course_root = self._course_root(course_id)
        course_manifest = self.load_course_manifest(course_id)
        workpiece_index = course_manifest.get("workpiece_index")
        if not isinstance(workpiece_index, dict) or workpiece_id not in workpiece_index:
            raise KeyError(f"workpiece {workpiece_id} is not indexed by course {course_id}")
        spec_path = ensure_within(course_root, course_root / str(workpiece_index[workpiece_id]))
        data = self._read_json(spec_path, course_root)
        data["path"] = spec_path.as_posix()
        return data

    def load_simulation_task_bundle(self, course_id: str, chapter_id: str, task_id: str) -> dict[str, Any]:
        course_root = self._course_root(course_id)
        course_manifest = self.load_course_manifest(course_id)
        chapter_root = self._chapter_root(course_root, course_manifest, chapter_id)
        chapter_manifest = self._read_json(chapter_root / "chapter_manifest.json", course_root)
        tasks = chapter_manifest.get("simulation_tasks")
        if not isinstance(tasks, list):
            raise KeyError(f"chapter {chapter_id} has no simulation tasks")
        for item in tasks:
            if isinstance(item, dict) and str(item.get("task_id") or "") == task_id:
                return self._simulation_task_bundle(chapter_root, item)
        raise KeyError(f"simulation task {task_id} is not indexed by chapter {chapter_id}")

    def load_simulation_rules(self, course_id: str) -> dict[str, dict[str, Any]]:
        course_root = self._course_root(course_id)
        course_manifest = self.load_course_manifest(course_id)
        rule_index = course_manifest.get("rule_index")
        if not isinstance(rule_index, dict):
            rule_index = {
                "hnc_instruction_table": "rules/hnc/hnc_instruction_table.md",
                "hnc_gcode_mapping": "rules/hnc/hnc_gcode_mapping.md",
                "hnc_programming_rules": "rules/hnc/hnc_programming_rules.md",
                "machine_profile": "rules/machine_profiles/default_lathe.json",
                "machine_limits": "rules/machine_profiles/machine_limits.json",
                "cutting_parameters": "rules/machine_profiles/cutting_parameters.json",
            }
        return {
            key: self._asset_ref(course_root, course_root, value)
            for key, value in rule_index.items()
            if isinstance(value, str)
        }

    def _course_root(self, course_id: str) -> Path:
        return ensure_within(self.resource_root, self.resource_root / safe_segment(course_id))

    def _chapter_root(self, course_root: Path, course_manifest: dict[str, Any], chapter_id: str) -> Path:
        chapter_index = course_manifest.get("chapter_index")
        if not isinstance(chapter_index, dict) or chapter_id not in chapter_index:
            raise KeyError(f"chapter {chapter_id} is not indexed by course manifest")
        return ensure_within(course_root, course_root / str(chapter_index[chapter_id]))

    def _chapter_assets(self, chapter_root: Path, chapter_manifest: dict[str, Any]) -> dict[str, Any]:
        assets: dict[str, Any] = {}
        for key in ("lecture", "reference_quiz", "practice"):
            section = chapter_manifest.get(key)
            if isinstance(section, dict):
                assets[key] = {
                    name: self._asset_ref(chapter_root, chapter_root, rel_path)
                    for name, rel_path in section.items()
                }
        if isinstance(chapter_manifest.get("videos"), list):
            assets["videos"] = [
                self._video_bundle(chapter_root, item)
                for item in chapter_manifest["videos"]
                if isinstance(item, dict)
            ]
        operation_tasks = chapter_manifest.get("operation_tasks")
        if isinstance(operation_tasks, list):
            assets["operation_tasks"] = [
                self._operation_task_bundle(chapter_root, item)
                for item in operation_tasks
                if isinstance(item, dict)
            ]
        return assets

    def _operation_task_bundle(self, chapter_root: Path, task_entry: dict[str, Any]) -> dict[str, Any]:
        manifest_path = ensure_within(chapter_root, chapter_root / str(task_entry["path"]))
        task_root = manifest_path.parent
        task_manifest = self._read_json(manifest_path, chapter_root)
        bundle = deepcopy(task_manifest)
        bundle["task_manifest_path"] = manifest_path.as_posix()
        bundle["task_path"] = task_root.as_posix()
        bundle["task_description"] = self._optional_asset_ref(task_root, task_manifest.get("task_description"))
        bundle["drawings"] = self._asset_ref_list(task_root, task_manifest.get("drawings"))
        bundle["standard_spec"] = self._optional_asset_ref(task_root, task_manifest.get("standard_spec"))
        bundle["review_rules"] = self._optional_asset_ref(task_root, task_manifest.get("review_rules"))
        bundle["standard_images"] = self._asset_ref_list(task_root, task_manifest.get("standard_images"))
        bundle["reference_quiz"] = self._optional_asset_ref(task_root, task_manifest.get("reference_quiz"))
        return bundle

    def _video_bundle(self, chapter_root: Path, video_entry: dict[str, Any]) -> dict[str, Any]:
        bundle = deepcopy(video_entry)
        if "path" in video_entry:
            bundle["file"] = self._asset_ref(chapter_root, chapter_root, video_entry["path"])
        if "transcript" in video_entry:
            bundle["transcript"] = self._asset_ref(chapter_root, chapter_root, video_entry["transcript"])
        return bundle

    def _asset_ref_list(self, base: Path, values: Any) -> list[dict[str, Any]]:
        if not isinstance(values, list):
            return []
        return [self._asset_ref(base, base, value) for value in values]

    def _optional_asset_ref(self, base: Path, rel_path: Any) -> dict[str, Any]:
        if not rel_path:
            return {}
        return self._asset_ref(base, base, rel_path)

    def _read_text_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        path = Path(str(asset["path"]))
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(path)
        return {
            "relative_path": asset.get("relative_path") or "",
            "path": path.as_posix(),
            "content": path.read_text(encoding="utf-8"),
        }

    def _simulation_task_bundle(self, chapter_root: Path, task_entry: dict[str, Any]) -> dict[str, Any]:
        manifest_path = ensure_within(chapter_root, chapter_root / str(task_entry["path"]))
        task_root = manifest_path.parent
        task_manifest = self._read_json(manifest_path, chapter_root)
        bundle = deepcopy(task_manifest)
        bundle["task_manifest_path"] = manifest_path.as_posix()
        bundle["task_path"] = task_root.as_posix()
        for key in ("question", "part_drawing", "reference_code", "standard_dimensions", "expected_result"):
            bundle[key] = self._asset_ref(task_root, task_root, task_manifest.get(key, ""))
        return bundle

    def _asset_ref(self, scope_root: Path, base: Path, rel_path: Any) -> dict[str, Any]:
        text = str(rel_path or "")
        path = ensure_within(scope_root, base / text)
        return {
            "relative_path": text.replace("\\", "/"),
            "path": path.as_posix(),
            "exists": path.exists(),
        }

    def _read_json(self, path: Path, scope_root: Path) -> dict[str, Any]:
        safe_path = ensure_within(scope_root, path)
        data = json.loads(safe_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"expected JSON object in {safe_path}")
        return data
