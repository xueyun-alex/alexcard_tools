---
name: main.py 五 Tab 模块拆分
overview: 将 main.py 按五个 Tab 拆分为独立模块(外加一个共享工具模块),main.py 只保留 App 主窗口骨架并统一引入各 Tab 启动,功能保持完全不变。
todos:
  - id: create-common
    content: 创建 tabs 包与 tabs/common.py(共享常量与工具函数,含 PROJECT_ROOT)
    status: completed
  - id: tab-aspect
    content: 拆出 tabs/tab_aspect.py(长宽比查看)
    status: completed
  - id: tab-process
    content: 拆出 tabs/tab_process.py(转JPG/亮度/三种海报贴入及框选对话框)
    status: completed
  - id: tab-files
    content: 拆出 tabs/tab_files.py(批量重命名/序号重命名/序号复制)
    status: completed
  - id: tab-gemini
    content: 拆出 tabs/tab_gemini.py(Gemini 会话、对话框与事件)
    status: completed
  - id: tab-xianguanjia
    content: 拆出 tabs/tab_xianguanjia.py(批量上线逻辑、草稿、对话框与事件)
    status: completed
  - id: rewrite-main
    content: 重写 main.py:仅保留 App 骨架、统一装配五个 Tab 与关闭逻辑
    status: completed
  - id: verify
    content: 编译检查并启动程序验证五个 Tab 功能入口完整
    status: completed
isProject: false
---

# main.py 五 Tab 模块拆分

## 目标结构

新建 `tabs/` 包,避免与根目录已有的 `xianguanjia.py`、`gemini_copy.py` 重名冲突:

- [tabs/__init__.py](tabs/__init__.py) — 空包文件
- [tabs/common.py](tabs/common.py) — 跨 Tab 共享的常量与纯函数
- [tabs/tab_aspect.py](tabs/tab_aspect.py) — Tab1 长宽比查看
- [tabs/tab_process.py](tabs/tab_process.py) — Tab2 图片处理
- [tabs/tab_files.py](tabs/tab_files.py) — Tab3 文件管理
- [tabs/tab_gemini.py](tabs/tab_gemini.py) — Tab4 gmini自动获取文案
- [tabs/tab_xianguanjia.py](tabs/tab_xianguanjia.py) — Tab5 闲管家上线
- [main.py](main.py) — 仅保留 `App` 主窗口 + 统一装配五个 Tab + `main()` 入口

## 各模块内容(均为原代码平移,不改逻辑)

### tabs/common.py
被两个以上 Tab 使用的部分:
- 常量:`IMAGE_FILETYPES`、`TEXT_FILETYPES`、`IMAGE_EXTENSIONS`
- 函数:`resource_path`、`list_images_in_dir`、`_image_stem`、`_is_main_image_stem`、`upload_pairs`、`_trim_float`、`prepare_for_jpeg`、`_add_tool_row`
- 项目根目录常量 `PROJECT_ROOT`(见下方「行为保持」)

### tabs/tab_aspect.py(Tab1)
- 逻辑:`aspect_ratio_text`、`line_for_path`、`build_report`
- 事件:`on_select_images`、`on_copy_all`

### tabs/tab_process.py(Tab2)
- 转 JPG:`jpg_output_path`、`convert_to_jpg`、`build_convert_report`
- 亮度:`adjust_brightness`、`brightness_output_path`、`save_image`、`adjust_image_brightness`、`build_brightness_report`
- 海报贴入:`PosterBox`、`fit_cover`、`paste_into_poster`、`poster_compose_output_path`、`compose_poster_pair/_single_multi/_combined` 及三个 `build_*_report`、`sorted_main_image_paths`、`normalize_poster_box`、`ask_poster_regions`、`ask_poster_regions_multi`、`_MULTI_BOX_COLORS`
- 事件:`on_convert_to_jpg`、`on_adjust_brightness`、`on_poster_compose`、`on_poster_single_multi`、`on_poster_combined`

### tabs/tab_files.py(Tab3)
- 重命名:`rename_stem_alternating`、`rename_stem`、`RenamePattern`、`parse_rename_pattern`、`rename_stem_from_pattern`、`rename_target_path`、`validate_rename_batch`、`rename_one_file`、`build_rename_preview`、`ask_rename_confirm`、`rename_images_batch`、`build_rename_report`
- 序号复制:`is_pure_sequence_stem`、`filter_sequence_copy_paths`、`copy_dest_path`、`validate_copy_batch`、`copy_one_file`、`build_copy_preview`、`ask_copy_confirm`、`copy_images_batch`、`build_copy_report`
- 事件:`on_rename_images`、`on_rename_by_pattern`、`on_copy_by_sequence`

### tabs/tab_gemini.py(Tab4)
- 会话:自持 `_gemini_busy` 标志与 `get_gemini_session()` 会话,提供 `close()` 供退出时调用
- 对话框:`ask_gemini_batch_dialog`
- 事件:`on_open_gemini`、`on_gemini_batch`

### tabs/tab_xianguanjia.py(Tab5)
- 数据类:`SpecPrice`、`BatchPublishParams`、`PublishItem`
- 草稿:`BATCH_PUBLISH_DRAFT_NAME`、`batch_publish_draft_path`、`load/save_batch_publish_draft`
- 逻辑:`parse_spec_prices`、`format_spec_prices`、`split_batch_copies`、`build_listing_description`、`_numeric_then_name_key`、`prepare_publish_items`
- 对话框:`ask_batch_publish_dialog`
- 会话:自持 `_xg_busy` 与 `get_xianguanjia_session()`,提供 `close()`
- 事件:`on_open_xianguanjia`、`on_batch_publish`

## Tab 与主窗口的接口

每个 Tab 模块定义一个 `tk.Frame` 子类(如 `AspectTab(tk.Frame)`),构造签名统一为 `__init__(self, notebook, app)`:
- `app` 即 `App` 实例,Tab 通过 `app.text`(报告区)、`app.append_report_line()`、`app.after()` 与主窗口交互(与现状等价,只是把 `self.xxx` 换成 `self.app.xxx`)
- Tab 内部用 `common._add_tool_row` 搭建按钮行,文案与顺序原样保留

## main.py(拆分后)

```python
from tabs.tab_aspect import AspectTab
from tabs.tab_process import ProcessTab
from tabs.tab_files import FilesTab
from tabs.tab_gemini import GeminiTab
from tabs.tab_xianguanjia import XianguanjiaTab

class App(tk.Tk):
    def __init__(self):
        ...  # 窗口标题/尺寸/图标、notebook、报告区 self.text
        notebook.add(AspectTab(notebook, self), text="长宽比查看")
        notebook.add(ProcessTab(notebook, self), text="图片处理")
        ...
    def append_report_line(self, line): ...
    def _on_app_close(self):  # 依次调用各 Tab 的 close()
```

保留 `main()` 与 `if __name__ == "__main__"` 入口不变。

## 行为保持要点

- `.batch_publish_last.json` 草稿文件目前存放在 `main.py` 同目录(仓库根)。搬到 `tabs/` 后若继续用 `__file__` 会指向 `tabs/` 子目录,导致旧草稿丢失。改为在 `tabs/common.py` 中定义 `PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`,草稿路径基于它计算,位置保持不变(PyInstaller 打包场景下与现状同样落在临时目录,行为一致)
- 会话初始化时机保持一致:`GeminiTab`/`XianguanjiaTab` 在构造时创建各自 session(与现在 `App.__init__` 中创建等价);窗口关闭时 `App._on_app_close` 调各 Tab 的 `close()` 执行 `submit_close()`,再 `destroy()`
- 打包入口仍是 `main.py`,新模块由 import 链自动被 PyInstaller 收集,`ImgAspectRatio.spec` 与 `build_exe.bat` 无需修改

## 验证

- `python -m py_compile` 编译全部新文件
- 启动 `python main.py`,确认五个 Tab 与全部按钮、说明文字齐全,报告区正常
