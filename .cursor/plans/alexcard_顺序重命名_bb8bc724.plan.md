---
name: Alexcard 顺序重命名
overview: 在“文件管理”Tab 新增“重命名文件…”按钮，将选中的图片按原文件名自然排序后，依次原地重命名为 `alexcard_1`、`alexcard_2`…，并保留各自扩展名。复用现有的冲突校验、预览确认、两阶段重命名和结果报告流程。
todos:
  - id: add-natural-rename
    content: 在 tabs/tab_files.py 添加自然排序及 alexcard_N 重命名入口并接入现有安全重命名流程
    status: completed
  - id: verify-rename
    content: 执行编译和临时文件场景验证，并检查文件管理 Tab 交互
    status: completed
isProject: false
---

# 新增 Alexcard 顺序重命名

## 实现
- 修改 [`tabs/tab_files.py`](tabs/tab_files.py)，增加文件名自然排序辅助逻辑，使数字片段按数值比较（例如 `2.jpg` 排在 `10.jpg` 前，普通名称也保持稳定、忽略大小写比较）。
- 在 `FilesTab` 的“文件管理”按钮区新增“重命名文件…”入口，继续使用现有 `IMAGE_FILETYPES`，仅选择图片。
- 新增事件处理方法：读取所选图片、按原文件名自然排序、生成 `alexcard_{序号}` 目标名，并保留每个源文件原扩展名。
- 复用 `validate_rename_batch`、`ask_rename_confirm` 和 `build_rename_report`：重命名前展示逐项预览；检测目录不一致或目标名被未选文件占用时中止；通过现有临时文件中转避免选中文件之间互相占名。
- 完成后将明细写入日志区，并弹窗显示成功/失败数量；取消选择或取消确认时不修改文件。

## 验证
- 编译检查 [`tabs/tab_files.py`](tabs/tab_files.py) 与应用入口。
- 使用临时图片验证：自然排序编号、大小写/数字混合名称、扩展名保留、已有 `alexcard_N` 文件参与换名、未选目标文件冲突、取消确认不执行。
- 启动应用确认“文件管理”Tab 新按钮、说明文字、预览和完成提示正常。