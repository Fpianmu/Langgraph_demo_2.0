from __future__ import annotations

import json

from playwright.sync_api import sync_playwright


def main() -> None:
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto("http://127.0.0.1:3000", wait_until="networkidle")
        page.get_by_label("Memory 用户中心").click()

        editor = page.locator(".profile-markdown-editor")
        editor.scroll_into_view_if_needed()
        editor.wait_for(state="visible")
        textarea = editor.locator("textarea")
        readonly = editor.locator("pre")
        save_button = editor.get_by_role("button", name="保存", exact=True)

        editable_content = textarea.input_value()
        full_content = readonly.text_content() or ""
        assert "## 学习背景" in editable_content
        assert "## 学习偏好" in editable_content
        assert "## 教师备注" in editable_content
        assert full_content.startswith("# 用户画像：")
        assert save_button.is_disabled()

        textarea.fill(editable_content + "\n")
        assert save_button.is_enabled()
        textarea.fill(editable_content)
        assert save_button.is_disabled()

        desktop = page.evaluate(
            """() => {
              const textarea = document.querySelector('.profile-markdown-editable textarea');
              const readonly = document.querySelector('.profile-markdown-readonly pre');
              const root = document.querySelector('.profile-markdown-editor');
              if (!textarea || !readonly || !root) throw new Error('profile editor missing');
              const left = textarea.getBoundingClientRect();
              const right = readonly.getBoundingClientRect();
              const style = getComputedStyle(textarea);
              return {
                fontFamily: style.fontFamily,
                fontSize: style.fontSize,
                editorWidth: root.getBoundingClientRect().width,
                textareaWidth: left.width,
                readonlyWidth: right.width,
                sameRow: Math.abs(left.top - right.top) < 4,
                horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth,
              };
            }"""
        )
        assert desktop["sameRow"]
        assert not desktop["horizontalOverflow"]
        assert "Microsoft YaHei" in desktop["fontFamily"]

        page.set_viewport_size({"width": 390, "height": 844})
        editor.scroll_into_view_if_needed()
        mobile = page.evaluate(
            """() => {
              const textarea = document.querySelector('.profile-markdown-editable textarea');
              const readonly = document.querySelector('.profile-markdown-readonly pre');
              if (!textarea || !readonly) throw new Error('profile editor missing');
              const editableBox = textarea.getBoundingClientRect();
              const readonlyBox = readonly.getBoundingClientRect();
              return {
                stacked: readonlyBox.top > editableBox.bottom,
                textareaWidth: editableBox.width,
                viewportWidth: window.innerWidth,
                horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth,
              };
            }"""
        )
        assert mobile["stacked"]
        assert not mobile["horizontalOverflow"]
        assert not console_errors, console_errors

        print(json.dumps({"desktop": desktop, "mobile": mobile}, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()
