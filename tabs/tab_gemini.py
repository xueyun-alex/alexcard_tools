"""Tab4 gmini自动获取文案：打开 Gemini、批量获取文案。"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

from gemini_copy import (
    GEMINI_STYLE_PROMPT,
    get_gemini_session,
    load_last_gemini_prompt,
    save_last_gemini_prompt,
)

from .common import IMAGE_FILETYPES, ScrollableTab, _add_tool_row


def ask_gemini_batch_dialog(
    parent: tk.Tk, default_prompt: str
) -> tuple[str, list[str]] | None:
    """提示词 + 选图对话框。确定返回 (prompt, paths)，取消返回 None。"""
    dlg = tk.Toplevel(parent)
    dlg.title("批量获取文案")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.minsize(520, 420)
    dlg.geometry("640x480")

    result: dict[str, object] = {"ok": False}

    tk.Label(dlg, text="提示词：", anchor="w").pack(fill=tk.X, padx=12, pady=(12, 4))
    prompt_box = scrolledtext.ScrolledText(dlg, wrap=tk.WORD, height=12, font=("", 10))
    prompt_box.pack(fill=tk.BOTH, expand=True, padx=12)
    prompt_box.insert("1.0", default_prompt)

    paths_var = tk.StringVar(value="未选择图片")
    selected: list[str] = []

    def on_pick() -> None:
        files = filedialog.askopenfilenames(
            parent=dlg,
            title="选择图片（可多选）",
            filetypes=IMAGE_FILETYPES,
        )
        if not files:
            return
        selected.clear()
        selected.extend(files)
        names = [os.path.basename(p) for p in selected]
        preview = "、".join(names[:8])
        if len(names) > 8:
            preview += f" 等共 {len(names)} 张"
        else:
            preview = f"已选 {len(names)} 张：" + preview
        paths_var.set(preview)

    pick_row = tk.Frame(dlg, padx=12, pady=8)
    pick_row.pack(fill=tk.X)
    tk.Button(pick_row, text="选择图片…", command=on_pick).pack(side=tk.LEFT)
    tk.Label(
        pick_row, textvariable=paths_var, anchor="w", justify="left", wraplength=480
    ).pack(side=tk.LEFT, padx=(8, 0), fill=tk.X, expand=True)

    def on_ok() -> None:
        prompt = prompt_box.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showerror("批量获取文案", "请输入提示词。", parent=dlg)
            return
        if not selected:
            messagebox.showerror("批量获取文案", "请至少选择一张图片。", parent=dlg)
            return
        result["ok"] = True
        result["prompt"] = prompt
        result["paths"] = list(selected)
        dlg.destroy()

    def on_cancel() -> None:
        dlg.destroy()

    btn_row = tk.Frame(dlg, padx=12, pady=12)
    btn_row.pack(fill=tk.X)
    tk.Button(btn_row, text="取消", command=on_cancel, width=10).pack(side=tk.RIGHT)
    tk.Button(btn_row, text="确定", command=on_ok, width=10).pack(
        side=tk.RIGHT, padx=(0, 8)
    )

    dlg.protocol("WM_DELETE_WINDOW", on_cancel)
    parent.wait_window(dlg)

    if not result.get("ok"):
        return None
    return str(result["prompt"]), list(result["paths"])  # type: ignore[arg-type]


class GeminiTab(ScrollableTab):
    def __init__(self, notebook: tk.Widget, app) -> None:
        super().__init__(notebook)
        self.app = app
        self._busy = False
        self._session = get_gemini_session()
        _add_tool_row(
            self.body,
            "打开 Gemini",
            self.on_open_gemini,
            "打开 Google AI Mode 网页，请先在此窗口登录；登录后勿关浏览器，再点「批量获取文案」。",
        )
        _add_tool_row(
            self.body,
            "批量获取文案…",
            self.on_gemini_batch,
            "弹出对话框输入提示词并选择图片，确定后依次发送给 Gemini；"
            "结果合并保存为所选图片目录下的 文案汇总.txt（仅【标题】【宝贝描述】【标签】，多条用 ======= 分隔）。",
        )

    def close(self) -> None:
        try:
            self._session.submit_close()
        except Exception:
            pass

    def on_open_gemini(self) -> None:
        if self._busy:
            messagebox.showinfo("打开 Gemini", "正在处理中，请稍候。")
            return
        self._busy = True
        self.app.append_report_line("正在打开 Gemini…")

        def on_progress(line: str) -> None:
            self.app.after(0, lambda l=line: self.app.append_report_line(l))

        def on_done() -> None:
            def finish() -> None:
                self._busy = False
                messagebox.showinfo(
                    "打开 Gemini",
                    "浏览器已打开。请先登录 Google，再点击「批量获取文案」。",
                )

            self.app.after(0, finish)

        def on_error(msg: str) -> None:
            def fail_ui() -> None:
                self._busy = False
                self.app.append_report_line(f"错误: {msg}")
                messagebox.showerror("打开 Gemini", msg)

            self.app.after(0, fail_ui)

        self._session.submit_open(
            on_progress=on_progress, on_done=on_done, on_error=on_error
        )

    def on_gemini_batch(self) -> None:
        if self._busy:
            messagebox.showinfo("批量获取文案", "正在处理中，请稍候。")
            return
        default_prompt = load_last_gemini_prompt(GEMINI_STYLE_PROMPT)
        result = ask_gemini_batch_dialog(self.app, default_prompt)
        if result is None:
            return
        prompt, paths = result
        save_error = save_last_gemini_prompt(prompt)
        if save_error:
            messagebox.showwarning("批量获取文案", save_error)
        self._busy = True
        self.app.text.delete("1.0", tk.END)
        self.app.text.insert(tk.END, f"开始处理 {len(paths)} 张图片…\n")

        def on_progress(line: str) -> None:
            self.app.after(0, lambda l=line: self.app.append_report_line(l))

        def on_done(lines: list[str], ok: int, fail: int, dest: str | None) -> None:
            def finish() -> None:
                self._busy = False
                if not lines:
                    self.app.append_report_line("没有处理结果。")
                detail = f"完成：成功 {ok} 张，失败 {fail} 张。"
                if dest:
                    detail += f"\n已写入：{dest}"
                elif ok == 0:
                    detail += "\n无成功文案可保存。"
                messagebox.showinfo("批量获取文案", detail)

            self.app.after(0, finish)

        def on_error(msg: str) -> None:
            def fail_ui() -> None:
                self._busy = False
                self.app.append_report_line(f"错误: {msg}")
                messagebox.showerror("批量获取文案", msg)

            self.app.after(0, fail_ui)

        self._session.submit_batch(
            paths,
            prompt,
            on_progress=on_progress,
            on_done=on_done,
            on_error=on_error,
        )
