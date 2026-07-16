"""ALEXCARD工具集主入口：装配五个 Tab 模块并启动主窗口。"""

import tkinter as tk
from tkinter import scrolledtext, ttk

from tabs.common import resource_path
from tabs.tab_aspect import AspectTab
from tabs.tab_process import ProcessTab
from tabs.tab_files import FilesTab
from tabs.tab_gemini import GeminiTab
from tabs.tab_xianguanjia import XianguanjiaTab


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ALEXCARD工具集")
        self.minsize(520, 360)
        self.geometry("720x520")
        try:
            self.iconbitmap(resource_path("draw.ico"))
        except tk.TclError:
            pass

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.X, padx=8, pady=8)

        notebook.add(AspectTab(notebook, self), text="长宽比查看")
        notebook.add(ProcessTab(notebook, self), text="图片处理")
        notebook.add(FilesTab(notebook, self), text="文件管理")
        self._gemini_tab = GeminiTab(notebook, self)
        notebook.add(self._gemini_tab, text="gmini自动获取文案")
        self._xg_tab = XianguanjiaTab(notebook, self)
        notebook.add(self._xg_tab, text="闲管家上线")

        self.protocol("WM_DELETE_WINDOW", self._on_app_close)
        self.text = scrolledtext.ScrolledText(
            self, wrap=tk.NONE, font=("Consolas", 10), undo=True
        )
        self.text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    def append_report_line(self, line: str) -> None:
        self.text.insert(tk.END, line + "\n")
        self.text.see(tk.END)

    def _on_app_close(self) -> None:
        self._gemini_tab.close()
        self._xg_tab.close()
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
