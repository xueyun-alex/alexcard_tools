"""闲鱼文案：通过 Playwright 操作 Google AI Mode（Gemini）生成标题/描述/标签。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def app_dir() -> str:
    """可写的应用根目录：源码旁，或打包后的 exe 所在目录。"""
    if _is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


LAST_GEMINI_PROMPT_NAME = ".gemini_last_prompt.txt"


def last_gemini_prompt_path(base_dir: str | None = None) -> str:
    return os.path.join(base_dir or app_dir(), LAST_GEMINI_PROMPT_NAME)


def load_last_gemini_prompt(
    default_prompt: str,
    *,
    storage_path: str | None = None,
) -> str:
    """读取上次确认使用的提示词；文件无效时退回默认提示词。"""
    path = storage_path or last_gemini_prompt_path()
    try:
        with open(path, encoding="utf-8") as f:
            prompt = f.read().strip()
        return prompt or default_prompt
    except OSError:
        return default_prompt


def save_last_gemini_prompt(
    prompt: str,
    *,
    storage_path: str | None = None,
) -> str | None:
    """原子保存提示词；成功返回 None，失败返回错误说明。"""
    text = prompt.strip()
    if not text:
        return "提示词为空，无法保存。"
    path = storage_path or last_gemini_prompt_path()
    temp_path = f"{path}.tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        os.replace(temp_path, path)
    except OSError as e:
        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        return f"保存上次提示词失败：{e}"
    return None


# 固定风格提示词（来自用户提供的 Google 搜索 q= 示例，去掉会话参数）
GEMINI_STYLE_PROMPT = (
    "【标题】姆巴佩球星卡 2026世界杯限定哈兰德球星卡双人对决忍者神龟VS魔人布欧同人海报大卡周边"
    "【宝贝描述】新双骄的终极宿命对决！绝代双骄梗的集大成神作，这波巅峰碰撞直接把绿苔荷尔蒙拉满！"
    "绝无仅有的神级神仙联动：高清定格“忍者神龟”姆巴佩与“魔人布欧”哈兰德的正面硬刚！"
    "左侧神龟战甲配超跑，右侧粉色布欧配维京战船，完美将足坛最火的网络热梗具象化。"
    "2026世界杯纪念细节：卡面精心绘制了2026 FIFA WORLD CUP官方图章、双星法国10号与挪威9号特制战袍，"
    "蓝红爆裂闪电交织，构图张力极其震撼。"
    "入砖挂墙首选：这不仅是一张创意球星卡，更是一幅极具收藏价值的微型艺术海报。"
    "强烈推荐作为卡架摆件或磁力卡砖锁死放在电脑桌旁，买到就是全网最帅的仔！"
    "（注：本品为粉丝自制同人创意整活周边，非官方正版球星卡。实物现货拍摄，手工定制制品售出不退不换，拍前请知悉~）"
    "【标签】 #姆巴佩球星卡 #哈兰德球星卡 #忍者神龟 #魔人布欧 #新绝代双骄 "
    "#2026世界杯周边 #自制卡周边 #整活同人卡 #桌面摆件 #闲鱼好物 "
    "模仿整个风格写个闲鱼售卖文案"
)

OUTPUT_FORMAT_INSTRUCTION = (
    "输出时必须只保留以下三个区段，不要使用 Markdown 代码块，"
    "不要添加前言、解释、总结或分隔线。三个区段都不能为空：\n"
    "【标题】\n"
    "商品标题\n"
    "【宝贝描述】\n"
    "完整商品描述\n"
    "【标签】\n"
    "#标签1 #标签2"
)
FORMAT_REPAIR_PROMPT = (
    "请只整理你上一条回答，不要重新分析图片，也不要省略已有内容。"
    "如果上一条没有明确标题，请根据上一条文案补出一个商品标题。"
    "只输出以下三个区段，禁止输出其他文字：\n"
    "【标题】\n商品标题\n"
    "【宝贝描述】\n完整商品描述\n"
    "【标签】\n#标签1 #标签2"
)


def build_generation_prompt(prompt: str) -> str:
    """在用户提示词后固定追加机器可解析的输出契约。"""
    return f"{prompt.strip()}\n\n{OUTPUT_FORMAT_INSTRUCTION}"


GOOGLE_AI_SEARCH_BASE = "https://www.google.com.hk/search"
# AI Mode 对话页（不带超长 q=，避免落到无输入框的结果页）
GOOGLE_AI_CHAT_URL = (
    f"{GOOGLE_AI_SEARCH_BASE}?udm=50&hl=zh-CN&atvm=2"
)
PROFILE_DIR_NAME = ".playwright-gemini-profile"
DEFAULT_TIMEOUT_MS = 120_000
GENERATION_POLL_SEC = 2.0

# Google AI Mode UI（参考可用自动化实现，DOM 变更时集中改这里）
TEXTAREA_SELECTOR = "textarea.ITIRGe"
IMAGE_BUTTON_SELECTOR = "button.hhGtFb"
IMAGE_INPUT_SELECTOR = "input[accept*='image']"
SEND_BUTTON_SELECTOR = 'button[data-xid="input-plate-send-button"]'
SEND_BUTTON_FALLBACKS = (
    SEND_BUTTON_SELECTOR,
    'button[aria-label="发送"]',
    'button[aria-label="Send"]',
    "[data-xid='input-plate-send-button']",
)
RESPONSE_BLOCK_SELECTOR = "[data-subtree='aimc']"
CONSENT_SELECTORS = (
    "#L2AGLb",
    "button:has-text('全部接受')",
    "button:has-text('接受全部')",
    "button:has-text('I agree')",
    "button:has-text('Accept all')",
)
UPLOAD_BUTTON_SELECTORS = [
    IMAGE_BUTTON_SELECTOR,
    'button[aria-label*="上传"]',
    'button[aria-label*="Upload"]',
    'button[aria-label*="Add image"]',
    'button[aria-label*="添加图片"]',
    'button[aria-label*="添加图片或文件"]',
    'button[aria-label*="Add images"]',
    '[aria-label*="Search by image"]',
    '[aria-label*="按图搜索"]',
]
FILE_INPUT_SELECTORS = [
    IMAGE_INPUT_SELECTOR,
    'input[accept*="image/jpeg"]',
    'input[type="file"]',
]
RESPONSE_MARKERS = ("【标题】", "【宝贝描述】", "【标签】")
BATCH_TXT_NAME = "文案汇总.txt"
BATCH_SEPARATOR = "======="
_SKIP_SELECTORS = ".HvurC, .Fsg96, .UrecDd, .FYF80, .DBd2Wb, .CxFouc"
_EXTRACT_RESPONSE_JS = f"""el => {{
    const skipSelectors = '{_SKIP_SELECTORS}';
    const tagMarker = /(?:^|\\n)\\s*(?:[#>*\\d.、()（）-]+\\s*)?(?:(?:【|\\[|（|\\()\\s*(?:标签|话题标签|商品标签|关键词|tags?|hashtags?)\\s*(?:】|\\]|）|\\))|(?:标签|话题标签|商品标签|关键词|tags?|hashtags?)\\s*[:：])/i;
    const walker = document.createTreeWalker(
        el,
        NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
    );
    let seenTags = false;
    let separator = null;
    let node;
    while ((node = walker.nextNode())) {{
        if (node.nodeType === Node.TEXT_NODE) {{
            if (tagMarker.test(node.textContent || '')) seenTags = true;
            continue;
        }}
        if (!seenTags || !(node instanceof Element)) continue;
        if (node.closest(skipSelectors)) continue;

        const tag = node.tagName.toLowerCase();
        const role = (node.getAttribute('role') || '').toLowerCase();
        const text = (node.innerText || node.textContent || '').trim();
        if (tag === 'hr' || role === 'separator'
                || /^(?:[-—–―─_=·•]\\s*){{3,}}$/.test(text)) {{
            separator = node;
            break;
        }}

        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        const topWidth = parseFloat(style.borderTopWidth) || 0;
        const bottomWidth = parseFloat(style.borderBottomWidth) || 0;
        const hasTopLine = topWidth > 0 && style.borderTopStyle !== 'none';
        const hasBottomLine = bottomWidth > 0
            && style.borderBottomStyle !== 'none';
        const hasBackground = style.backgroundColor !== 'transparent'
            && style.backgroundColor !== 'rgba(0, 0, 0, 0)';
        const flatLine = text === '' && rect.height <= 8
            && (hasTopLine || hasBottomLine || hasBackground);
        if (rect.width >= 80 && (flatLine || hasTopLine)) {{
            separator = node;
            break;
        }}
    }}

    if (separator) separator.setAttribute('data-copy-cut', '1');
    const clone = el.cloneNode(true);
    if (separator) separator.removeAttribute('data-copy-cut');
    clone.querySelectorAll('{_SKIP_SELECTORS}').forEach(n => n.remove());
    const cut = clone.querySelector('[data-copy-cut="1"]');
    if (cut) {{
        let current = cut;
        let removeCurrent = true;
        while (current && current !== clone) {{
            const parent = current.parentNode;
            let sibling = current.nextSibling;
            while (sibling) {{
                const next = sibling.nextSibling;
                sibling.remove();
                sibling = next;
            }}
            if (removeCurrent) current.remove();
            removeCurrent = false;
            current = parent;
        }}
    }}
    return clone.innerText.trim();
}}"""

_TEXT_SEPARATOR_RE = re.compile(
    r"(?m)^\s*(?:[-—–―─_=·•]\s*){3,}\s*$"
)
_GENERIC_PREAMBLE_RE = re.compile(
    r"^(?:以下|下面|为你|根据|可以|当然|好的|没问题|"
    r"(?:闲鱼|商品)?文案(?:如下|内容))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedCopy:
    title: str
    description: str
    tags: str


def profile_dir(base_dir: str | None = None) -> str:
    root = base_dir or app_dir()
    return os.path.join(root, PROFILE_DIR_NAME)


def build_search_url(prompt: str = GEMINI_STYLE_PROMPT) -> str:
    """保留兼容；实际流程改走 AI Mode 对话页 + textarea 填提示词。"""
    return (
        f"{GOOGLE_AI_SEARCH_BASE}"
        f"?udm=50&hl=zh-CN&q={quote(prompt)}"
    )


def batch_txt_path(image_paths: list[str]) -> str:
    """所选图片公共父目录下的 文案汇总.txt；跨盘符时退回第一张图所在目录。"""
    if not image_paths:
        raise ValueError("image_paths 为空")
    dirs = [os.path.dirname(os.path.abspath(p)) for p in image_paths]
    try:
        common = os.path.commonpath(dirs)
    except ValueError:
        common = dirs[0]
    if not os.path.isdir(common):
        common = dirs[0]
    return os.path.join(common, BATCH_TXT_NAME)


_SECTION_ALIASES = {
    "title": (
        "商品标题",
        "宝贝标题",
        "文案标题",
        "闲鱼标题",
        "product title",
        "标题",
        "title",
    ),
    "description": (
        "宝贝描述",
        "商品描述",
        "产品描述",
        "商品文案",
        "宝贝文案",
        "description",
        "正文",
        "描述",
        "desc",
        "copy",
    ),
    "tags": (
        "话题标签",
        "商品标签",
        "hashtags",
        "keywords",
        "关键词",
        "关键字",
        "标签",
        "hashtag",
        "tags",
        "tag",
    ),
}


def _normalize_alias(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value).casefold()


_ALIAS_TO_SECTION = {
    _normalize_alias(alias): section
    for section, aliases in _SECTION_ALIASES.items()
    for alias in aliases
}
_SECTION_ALIAS_PATTERN = "|".join(
    re.escape(alias)
    for alias in sorted(
        (alias for aliases in _SECTION_ALIASES.values() for alias in aliases),
        key=len,
        reverse=True,
    )
)
_SECTION_MARKER_RE = re.compile(
    rf"(?:[【\[\(（「『]\s*(?P<bracket>{_SECTION_ALIAS_PATTERN})\s*"
    rf"[】\]\)）」』]\s*[:：]?"
    rf"|(?m:^[ \t]*(?:(?:#{{1,6}}|[-*>])\s*|\d+[.、)]\s*)?"
    rf"(?P<line>{_SECTION_ALIAS_PATTERN})\s*"
    rf"(?:[:：\-—]\s*|(?=$)))"
    rf"|(?<!\w)(?P<inline>{_SECTION_ALIAS_PATTERN})\s*[:：]\s*)",
    re.IGNORECASE,
)


def _clean_response_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"(?m)^\s*```(?:json|markdown|text)?\s*$", "", text, flags=re.I)
    text = re.sub(r"(?m)^\s*```\s*$", "", text)
    return text.replace("**", "").replace("__", "").strip()


def _find_section_markers(text: str) -> list[tuple[int, int, str]]:
    markers: list[tuple[int, int, str]] = []
    for match in _SECTION_MARKER_RE.finditer(text):
        label = (
            match.group("bracket")
            or match.group("line")
            or match.group("inline")
        )
        section = _ALIAS_TO_SECTION.get(_normalize_alias(label))
        if section:
            markers.append((match.start(), match.end(), section))
    return markers


def _extract_labeled_sections(
    text: str,
    markers: list[tuple[int, int, str]],
) -> dict[str, str]:
    sections: dict[str, str] = {}
    for index, (_, end, section) in enumerate(markers):
        next_start = markers[index + 1][0] if index + 1 < len(markers) else len(text)
        body = text[end:next_start].strip().lstrip(":：-—").strip()
        if body and section not in sections:
            sections[section] = body
    return sections


def _json_value_to_text(value: object) -> str:
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _extract_json_sections(text: str) -> dict[str, str]:
    candidates = [text.strip()]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.I | re.S)
    candidates.extend(fenced)
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        sections: dict[str, str] = {}
        for key, value in data.items():
            section = _ALIAS_TO_SECTION.get(_normalize_alias(str(key)))
            content = _json_value_to_text(value)
            if section and content:
                sections[section] = content
        if sections:
            return sections
    return {}


def _recover_unlabeled_title(prefix: str) -> str | None:
    """标题标记缺失时，取描述区段前最后一条非套话文本作为标题。"""
    candidates: list[str] = []
    for raw_line in prefix.splitlines():
        line = raw_line.strip()
        line = re.sub(r"^(?:[#*>\-]+\s*|\d+[.、)]\s*)", "", line)
        line = re.sub(
            r"^(?:(?:商品|宝贝|文案|闲鱼)?标题|title)\s*[:：]\s*",
            "",
            line,
            flags=re.I,
        )
        line = line.strip().strip("*").strip()
        if not line:
            continue
        if _GENERIC_PREAMBLE_RE.search(line):
            parts = re.split(r"[:：]", line, maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                continue
            line = parts[1].strip()
            if _GENERIC_PREAMBLE_RE.search(line):
                continue
        candidates.append(line)
    return candidates[-1] if candidates else None


def _normalize_copy_window(raw: str) -> str:
    """清理回复，并截断标签区段之后的文本分隔线和页脚。"""
    text = _clean_response_text(raw)
    if not text:
        return ""
    markers = _find_section_markers(text)
    tag_starts = [end for _, end, section in markers if section == "tags"]
    search_start = tag_starts[0] if tag_starts else text.find("#")
    if search_start >= 0:
        separator = _TEXT_SEPARATOR_RE.search(text, search_start)
        if separator:
            text = text[: separator.start()].rstrip()
    return text.strip()


def _trim_tags_footer(tags: str) -> str:
    """标签出现后，丢弃首个非标签页脚行，防止保存分隔线下方内容。"""
    lines = tags.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    if not any("#" in line for line in lines):
        return tags.strip()

    kept: list[str] = []
    tag_started = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if tag_started:
                continue
            continue
        if "#" in stripped:
            tag_started = True
            kept.append(stripped)
            continue
        if tag_started:
            break
    return "\n".join(kept).strip()


def _extract_hashtag_tags(text: str) -> str | None:
    tags = re.findall(r"(?<![\w#])#[^\s#，,。；;！!？?]+", text)
    if not tags:
        return None
    return " ".join(dict.fromkeys(tags))


def _remove_hashtag_tail(text: str) -> str:
    """标签标记缺失时，避免把末尾 #标签 一并放进宝贝描述。"""
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        hash_index = line.find("#")
        if hash_index >= 0:
            prefix = line[:hash_index].strip()
            if prefix:
                kept.append(prefix)
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _clean_unlabeled_line(line: str) -> str:
    line = re.sub(r"^(?:[#*>\-]+\s*|\d+[.、)]\s*)", "", line.strip())
    return line.strip().strip("*").strip()


def _extract_unlabeled_sections(text: str) -> dict[str, str]:
    """完全无字段名时：首条有效文本作标题，中间正文作描述，#内容作标签。"""
    tags = _extract_hashtag_tags(text)
    content = _remove_hashtag_tail(text) if tags else text
    lines: list[str] = []
    for raw_line in content.splitlines():
        line = _clean_unlabeled_line(raw_line)
        if not line or _GENERIC_PREAMBLE_RE.search(line):
            continue
        lines.append(line)
    if len(lines) < 2:
        return {"tags": tags} if tags else {}
    result = {
        "title": lines[0],
        "description": "\n".join(lines[1:]).strip(),
    }
    if tags:
        result["tags"] = tags
    return result


def parse_gemini_copy(raw: str) -> ParsedCopy:
    """兼容标准标记、普通字段、Markdown、JSON 和字段名缺失的回复。"""
    text = _normalize_copy_window(raw)
    if not text:
        raise ValueError("回复为空")

    sections = _extract_json_sections(text)
    markers = _find_section_markers(text)
    sections.update(_extract_labeled_sections(text, markers))

    title = sections.get("title", "").strip()
    description = sections.get("description", "").strip()
    tags = sections.get("tags", "").strip()

    if not title and markers:
        description_markers = [
            start for start, _, section in markers if section == "description"
        ]
        prefix_end = description_markers[0] if description_markers else (
            markers[0][0] if markers else len(text)
        )
        title = _recover_unlabeled_title(text[:prefix_end]) or ""

    # 只有标题和标签字段时，标题字段常同时包含“首行标题 + 后续描述”。
    if title and not description and "\n" in title:
        title_lines = [line.strip() for line in title.splitlines() if line.strip()]
        if len(title_lines) >= 2:
            title = title_lines[0]
            description = "\n".join(title_lines[1:])

    if not tags:
        tags = _extract_hashtag_tags(text) or ""
    if description and "#" in description:
        description = _remove_hashtag_tail(description)

    # 仅在完全没有任何字段标记时启用整段猜测；若已有部分字段，
    # 不把“宝贝描述”误当标题，交给自动格式修复补齐更可靠。
    heuristic = _extract_unlabeled_sections(text) if not markers and not sections else {}
    title = title or heuristic.get("title", "")
    description = description or heuristic.get("description", "")
    tags = tags or heuristic.get("tags", "")
    tags = _trim_tags_footer(tags) if tags else ""

    missing: list[str] = []
    if not title:
        missing.append("【标题】")
    if not description:
        missing.append("【宝贝描述】")
    if not tags:
        missing.append("【标签】")
    if missing:
        raise ValueError("缺少" + "、".join(missing))

    assert title and description and tags
    return ParsedCopy(title=title, description=description, tags=tags)


def _has_complete_section_markers(text: str) -> bool:
    sections = set(_extract_json_sections(_clean_response_text(text)))
    sections.update(section for _, _, section in _find_section_markers(text))
    return {"title", "description", "tags"}.issubset(sections)


def format_description_paragraphs(description: str) -> str:
    """段与段之间空一行。既支持原文已有空行，也支持单换行分段。"""
    normalized = description.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\n\n" in normalized:
        parts = [p.strip() for p in re.split(r"\n\s*\n", normalized) if p.strip()]
    else:
        parts = [p.strip() for p in normalized.split("\n") if p.strip()]
    return "\n\n".join(parts)


def format_copy_document(parsed: ParsedCopy) -> str:
    desc = format_description_paragraphs(parsed.description)
    return (
        f"【标题】\n{parsed.title.strip()}\n\n"
        f"【宝贝描述】\n{desc}\n\n"
        f"【标签】\n{parsed.tags.strip()}\n"
    )


def write_batch_copy_txt(dest: str, documents: list[str]) -> str:
    """将多条文案用 ======= 拼成一个文件并覆盖写入。"""
    parts = [d.replace("\r\n", "\n").replace("\r", "\n").strip() for d in documents]
    content = f"\n{BATCH_SEPARATOR}\n".join(parts) + "\n"
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return dest


def _dismiss_consent(page) -> None:
    for sel in CONSENT_SELECTORS:
        loc = page.locator(sel)
        if loc.count() == 0:
            continue
        try:
            loc.first.click(timeout=2_000)
            page.wait_for_timeout(500)
            return
        except Exception:
            continue


def _ai_mode_unavailable(page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return False
    return "无法使用 AI 模式" in text or "can't use AI Mode" in text


def _safe_goto_ai(page) -> None:
    """打开 AI Mode；登录跳转会打断 goto，改为等待最终页加载。"""
    try:
        page.goto(GOOGLE_AI_CHAT_URL, wait_until="domcontentloaded", timeout=60_000)
    except Exception as e:
        msg = str(e).lower()
        if "interrupted" not in msg and "navigation" not in msg:
            raise
        try:
            page.wait_for_load_state("domcontentloaded", timeout=60_000)
        except Exception:
            pass
    page.wait_for_timeout(1_200)


def _chat_input_ready(page) -> bool:
    try:
        return page.locator(TEXTAREA_SELECTOR).count() > 0
    except Exception:
        return False


def _ensure_on_chat(page) -> None:
    """已在对话页则不刷新；否则再导航一次（容忍登录重定向）。"""
    if not _chat_input_ready(page):
        _safe_goto_ai(page)
    _ensure_chat_ready(page)


def _ensure_chat_ready(page) -> None:
    _dismiss_consent(page)
    if _ai_mode_unavailable(page):
        raise RuntimeError(
            "当前账号/地区无法使用 Google AI 模式。"
            "请在弹出浏览器中登录可用的 Google 账号后重试。"
        )
    url = ""
    try:
        url = page.url or ""
    except Exception:
        pass
    if "accounts.google.com" in url:
        raise RuntimeError(
            "当前在 Google 登录页。请先在浏览器中完成登录，再点「批量获取文案」。"
        )
    # 只要 DOM 里有输入框即可（Google 常把 textarea 标成 not visible）
    page.wait_for_selector(TEXTAREA_SELECTOR, state="attached", timeout=30_000)
    _reveal_prompt_input(page)


def _reveal_prompt_input(page) -> None:
    """点击输入区容器，尽量把 textarea 滚入视野并聚焦。"""
    for sel in (
        "div.Txyg0d",
        'div[placeholder="尽情提问"]',
        "textarea.ITIRGe",
    ):
        loc = page.locator(sel)
        if loc.count() == 0:
            continue
        try:
            loc.last.scroll_into_view_if_needed(timeout=3_000)
        except Exception:
            pass
        try:
            loc.last.click(force=True, timeout=3_000)
            page.wait_for_timeout(250)
            return
        except Exception:
            continue


def _prompt_textarea(page):
    """优先选可见的 textarea；否则退回第一个已挂载节点。"""
    loc = page.locator(TEXTAREA_SELECTOR)
    n = loc.count()
    if n == 0:
        raise RuntimeError("未找到提示词输入框 textarea.ITIRGe")
    for i in range(n):
        el = loc.nth(i)
        try:
            if el.is_visible():
                return el
        except Exception:
            continue
    # 常见：只有一个但 Playwright 判定不可见 —— 用第一个
    return loc.first


def _fill_prompt(page, prompt: str) -> None:
    _reveal_prompt_input(page)
    box = _prompt_textarea(page)
    try:
        box.scroll_into_view_if_needed(timeout=3_000)
    except Exception:
        pass
    try:
        box.click(force=True, timeout=5_000)
    except Exception:
        pass
    # 不依赖可见性：force fill + JS 写入并触发 input
    try:
        box.fill(prompt, force=True, timeout=10_000)
    except Exception:
        pass
    box.evaluate(
        """(el, text) => {
            el.focus();
            el.value = text;
            el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'a' }));
        }""",
        prompt,
    )
    page.wait_for_timeout(200)


def _copy_image_to_clipboard(image_path: str) -> None:
    """将图片写入 Windows 剪贴板，供 Ctrl+V 粘贴。"""
    import subprocess
    import sys

    if sys.platform != "win32":
        raise RuntimeError("当前仅支持在 Windows 上将图片写入剪贴板。")

    abs_path = os.path.abspath(image_path)
    # PowerShell + WinForms 剪贴板（比裸 ctypes 更稳）
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        f"$img = [System.Drawing.Image]::FromFile('{abs_path.replace(chr(39), chr(39)+chr(39))}'); "
        "try { [System.Windows.Forms.Clipboard]::SetImage($img) } finally { $img.Dispose() }"
    )
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-STA",  # 剪贴板需要 STA
            "-Command",
            ps,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        # 回退：ctypes CF_DIB
        try:
            _copy_image_to_clipboard_ctypes(abs_path)
            return
        except Exception as e2:
            raise RuntimeError(
                f"复制图片到剪贴板失败: {detail or e2}"
            ) from e2


def _copy_image_to_clipboard_ctypes(image_path: str) -> None:
    import ctypes
    from ctypes import wintypes
    from io import BytesIO

    from PIL import Image

    with Image.open(image_path) as im:
        rgb = im.convert("RGB")
        buf = BytesIO()
        rgb.save(buf, "BMP")
        dib = buf.getvalue()[14:]

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_DIB = 8
    GMEM_MOVEABLE = 0x0002

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL

    if not user32.OpenClipboard(None):
        raise RuntimeError("无法打开剪贴板")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
        if not handle:
            raise RuntimeError("GlobalAlloc 失败")
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            raise RuntimeError("GlobalLock 失败")
        ctypes.memmove(ptr, dib, len(dib))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_DIB, handle):
            kernel32.GlobalFree(handle)
            raise RuntimeError("SetClipboardData 失败")
    finally:
        user32.CloseClipboard()


def _paste_image_from_clipboard(page) -> None:
    """聚焦输入框后 Ctrl+V 粘贴剪贴板中的图片。"""
    _reveal_prompt_input(page)
    box = _prompt_textarea(page)
    try:
        box.click(force=True, timeout=5_000)
    except Exception:
        pass
    page.wait_for_timeout(200)
    # Chromium on Windows: Control+v
    modifier = "Control"
    page.keyboard.down(modifier)
    page.keyboard.press("v")
    page.keyboard.up(modifier)
    page.wait_for_timeout(800)


def _send_button_locator(page):
    for sel in SEND_BUTTON_FALLBACKS:
        loc = page.locator(sel)
        if loc.count() > 0:
            return loc.last
    return page.locator(SEND_BUTTON_SELECTOR).last


def _is_send_ready(page) -> bool:
    """右下角发送（向上箭头）是否已可用。"""
    btn = _send_button_locator(page)
    try:
        if btn.count() == 0:
            return False
    except Exception:
        return False
    try:
        if btn.get_attribute("disabled") is not None:
            return False
        aria = (btn.get_attribute("aria-disabled") or "").lower()
        if aria in ("true", "1"):
            return False
        # Google 有时用 tabindex=-1 / 父级灰态；能点且未 disabled 即视为可用
        return True
    except Exception:
        return False


def _wait_send_ready(page, timeout_ms: int = 30_000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if _is_send_ready(page):
            # 图片预览可能还需一小会
            page.wait_for_timeout(400)
            if _is_send_ready(page):
                return
        time.sleep(0.4)
    raise RuntimeError(
        "粘贴图片后发送按钮仍不可用。请确认剪贴板图片已成功粘贴到输入框。"
    )


def _click_send(page) -> None:
    _wait_send_ready(page)
    for sel in SEND_BUTTON_FALLBACKS:
        send = page.locator(sel)
        if send.count() == 0:
            continue
        n = send.count()
        for i in range(n - 1, -1, -1):
            btn = send.nth(i)
            try:
                if btn.is_visible():
                    btn.click(timeout=10_000)
                    return
            except Exception:
                continue
        try:
            send.last.click(force=True, timeout=10_000)
            return
        except Exception:
            continue
    try:
        _prompt_textarea(page).press("Enter")
    except Exception as e:
        raise RuntimeError(f"无法点击发送按钮: {e}") from e


def _attach_image_via_clipboard(page, image_path: str) -> None:
    """把图片放进剪贴板，在输入框 Ctrl+V 粘贴。"""
    try:
        _copy_image_to_clipboard(image_path)
    except Exception as e:
        raise RuntimeError(f"复制图片到剪贴板失败: {e}") from e
    _paste_image_from_clipboard(page)
    _wait_send_ready(page)


def _extract_aimc_text(page) -> str:
    blocks = page.locator(RESPONSE_BLOCK_SELECTOR)
    n = blocks.count()
    if n == 0:
        return ""
    block = blocks.nth(n - 1)
    main_col = block.locator("[data-container-id='main-col']")
    target = main_col if main_col.count() > 0 else block
    try:
        return target.evaluate(_EXTRACT_RESPONSE_JS) or ""
    except Exception:
        try:
            return target.inner_text(timeout=3_000).strip()
        except Exception:
            return ""


def _extract_reply_text(page) -> str:
    """优先取 AI Mode 回复块，否则回退整页文本。"""
    aimc = _extract_aimc_text(page)
    # 回复块存在时必须直接使用；整页还包含用户提示词中的格式示例，
    # 若回复使用了其他字段格式，回退整页会误把提示词当成回答。
    if aimc:
        return aimc.strip()
    try:
        body = page.locator("body").inner_text(timeout=5_000)
    except Exception:
        body = ""
    if all(m in body for m in RESPONSE_MARKERS):
        idx = body.find("【标题】")
        if idx >= 0:
            return body[idx:].strip()
    return (aimc or body).strip()


def _wait_for_copy_ready(
    page,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    *,
    previous: str = "",
) -> str:
    """等待新回复稳定：与发送前文本不同，且内容不再变化。"""
    deadline = time.monotonic() + timeout_ms / 1000.0
    last = ""
    stable = 0
    prev = (previous or "").strip()
    while time.monotonic() < deadline:
        try:
            current = _extract_reply_text(page)
        except Exception:
            current = ""
        cur = (current or "").strip()
        if len(cur) < 8:
            time.sleep(GENERATION_POLL_SEC)
            continue
        # 同一会话多轮：必须等到与发送前不同的新回复
        if prev and cur == prev:
            time.sleep(GENERATION_POLL_SEC)
            continue
        need_stable = 2 if _has_complete_section_markers(cur) else 3
        if cur == last:
            stable += 1
            if stable >= need_stable:
                return cur
        else:
            stable = 0
            last = cur
        time.sleep(GENERATION_POLL_SEC)
    if last.strip() and last.strip() != prev:
        return last
    raise TimeoutError("超时未生成")


def process_one_image(
    page, image_path: str, prompt: str = GEMINI_STYLE_PROMPT
) -> ParsedCopy:
    """填提示词 → 剪贴板粘贴图片 → 等发送可用 → 发送 → 解析三段。不写文件。"""
    _ensure_on_chat(page)

    previous = ""
    try:
        previous = _extract_aimc_text(page)
    except Exception:
        previous = ""

    try:
        _copy_image_to_clipboard(image_path)
    except Exception as e:
        raise RuntimeError(f"复制图片到剪贴板失败: {e}") from e

    _fill_prompt(page, build_generation_prompt(prompt))
    try:
        _paste_image_from_clipboard(page)
        _wait_send_ready(page)
    except Exception as e:
        raise RuntimeError(f"粘贴图片失败: {e}") from e

    _click_send(page)

    raw = _wait_for_copy_ready(page, previous=previous)
    try:
        return parse_gemini_copy(raw)
    except ValueError as first_error:
        # 同一会话仍保留图片和上一条回答；让 Gemini 只重排格式，再解析一次。
        _fill_prompt(page, FORMAT_REPAIR_PROMPT)
        _click_send(page)
        repaired_raw = _wait_for_copy_ready(page, previous=raw)
        try:
            return parse_gemini_copy(repaired_raw)
        except ValueError as repair_error:
            raise ValueError(
                f"原回复解析失败（{first_error}）；"
                f"自动格式修复后仍失败（{repair_error}）"
            ) from repair_error


ProgressCallback = Callable[[str], None]
DoneCallback = Callable[[], None]
ErrorCallback = Callable[[str], None]
BatchDoneCallback = Callable[[list[str], int, int, str | None], None]


def _is_missing_browser_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "executable doesn't exist" in msg
        or "playwright install" in msg
        or ("doesn't exist" in msg and "chromium" in msg)
    )


def _manual_chromium_hint() -> str:
    """打包后 sys.executable 是 exe，不能再用它跑 -m playwright。"""
    return "python -m playwright install chromium"


def _browsers_dir() -> str:
    """浏览器下载目录固定到 exe/项目旁，便于打包环境读写。"""
    path = os.path.join(app_dir(), ".playwright-browsers")
    os.makedirs(path, exist_ok=True)
    return path


def _prepare_browsers_env() -> None:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browsers_dir()


def _chromium_install_command() -> list[str]:
    """通过 Playwright 自带 node/cli 安装浏览器，避免冻结 exe 被当成 Python。"""
    from playwright._impl._driver import compute_driver_executable

    node, cli = compute_driver_executable()
    return [node, cli, "install", "chromium"]


def _system_browser_channels() -> tuple[str, ...]:
    """Windows 优先用本机 Edge/Chrome，打包 exe 无需再下 Playwright Chromium。"""
    if sys.platform == "win32":
        return ("msedge", "chrome")
    return ("chrome", "msedge")


def ensure_chromium_installed(on_progress: ProgressCallback | None = None) -> None:
    """
    确保能启动浏览器。
    优先依赖系统 Edge/Chrome；仅在都不可用时才安装 Playwright Chromium。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "未安装 playwright。请执行: pip install playwright && "
            + _manual_chromium_hint()
        ) from e

    _prepare_browsers_env()

    # 系统浏览器可用则无需安装 Chromium
    with sync_playwright() as p:
        for channel in _system_browser_channels():
            try:
                browser = p.chromium.launch(channel=channel, headless=True)
                browser.close()
                return
            except Exception:
                continue

        exe = p.chromium.executable_path
        if os.path.exists(exe):
            return

    if on_progress:
        on_progress("未检测到本机 Edge/Chrome，正在安装 Chromium，请稍候…")

    from playwright._impl._driver import get_driver_env

    env = get_driver_env()
    env["PLAYWRIGHT_BROWSERS_PATH"] = _browsers_dir()
    try:
        cmd = _chromium_install_command()
    except Exception as e:
        raise RuntimeError(
            "无法定位 Playwright 驱动。请安装 Microsoft Edge 或 Google Chrome，"
            "或手动执行: " + _manual_chromium_hint()
        ) from e

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    detail = (result.stderr or result.stdout or "").strip()
    if result.returncode != 0:
        raise RuntimeError(
            "自动安装 Chromium 失败。请安装 Microsoft Edge / Google Chrome，"
            "或手动执行: "
            + _manual_chromium_hint()
            + (f"\n{detail}" if detail else "")
        )

    _prepare_browsers_env()
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            raise RuntimeError(
                "Chromium 安装后仍不可用。请安装 Microsoft Edge / Google Chrome，"
                "或手动执行: "
                + _manual_chromium_hint()
                + (f"\n{detail}" if detail else "")
            )


def _launch_persistent_context(p, user_data: str, headless: bool):
    """优先 channel=本机 Edge/Chrome；都失败再退回 Playwright Chromium。"""
    _prepare_browsers_env()
    common = {
        "headless": headless,
        # None：随窗口大小自适应，有头模式下可用滚轮正常滚动页面
        "viewport": None,
        "accept_downloads": True,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    errors: list[str] = []
    for channel in (*_system_browser_channels(), None):
        kwargs = dict(common)
        if channel:
            kwargs["channel"] = channel
        try:
            return p.chromium.launch_persistent_context(user_data, **kwargs)
        except Exception as e:
            label = channel or "chromium"
            errors.append(f"{label}: {e}")
            continue
    raise RuntimeError(
        "无法启动浏览器（已尝试 Edge / Chrome / Chromium）。\n"
        + "\n".join(errors)
    )


class GeminiBrowserSession:
    """
    在专用后台线程中串行执行 open / run_batch，保持同一 Playwright 上下文。
    主线程通过 submit_* 投递任务，用回调拿结果。
    """

    def __init__(self, profile_base: str | None = None, headless: bool = False) -> None:
        import queue

        self._profile_base = profile_base
        self._headless = headless
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._playwright = None
        self._context = None
        self._page = None

    def start_worker(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="gemini-pw")
        self._thread.start()

    def submit_open(
        self,
        *,
        on_progress: ProgressCallback | None = None,
        on_done: DoneCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self.start_worker()
        self._q.put(("open", on_progress, on_done, on_error))

    def submit_batch(
        self,
        image_paths: list[str],
        prompt: str,
        *,
        on_progress: ProgressCallback | None = None,
        on_done: BatchDoneCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self.start_worker()
        self._q.put(("batch", list(image_paths), prompt, on_progress, on_done, on_error))

    def submit_close(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            return
        self._q.put(("close",))

    def _loop(self) -> None:
        while True:
            item = self._q.get()
            try:
                cmd = item[0]
                if cmd == "open":
                    _, on_progress, on_done, on_error = item
                    try:
                        self._do_open(on_progress)
                        if on_done:
                            on_done()
                    except Exception as e:
                        if on_error:
                            on_error(str(e))
                elif cmd == "batch":
                    _, paths, prompt, on_progress, on_done, on_error = item
                    try:
                        lines, ok, fail, dest = self._do_batch(
                            paths, prompt, on_progress
                        )
                        if on_done:
                            on_done(lines, ok, fail, dest)
                    except Exception as e:
                        if on_error:
                            on_error(str(e))
                elif cmd == "close":
                    self._do_close()
                    break
            finally:
                self._q.task_done()

    def _context_alive(self) -> bool:
        if self._context is None or self._page is None:
            return False
        try:
            _ = self._page.url
            return True
        except Exception:
            return False

    def _do_open(self, on_progress: ProgressCallback | None) -> None:
        from playwright.sync_api import sync_playwright

        def emit(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        ensure_chromium_installed(on_progress=emit)

        if self._context_alive():
            assert self._page is not None
            _safe_goto_ai(self._page)
            try:
                self._page.bring_to_front()
            except Exception:
                pass
            emit("已打开 Gemini 页面，请登录后使用「批量获取文案」。")
            return

        self._do_close()
        user_data = profile_dir(self._profile_base)
        self._playwright = sync_playwright().start()
        try:
            self._context = _launch_persistent_context(
                self._playwright, user_data, self._headless
            )
        except Exception as e:
            if _is_missing_browser_error(e):
                emit("检测到 Chromium 缺失，正在重试安装…")
                ensure_chromium_installed(on_progress=emit)
                self._context = _launch_persistent_context(
                    self._playwright, user_data, self._headless
                )
            else:
                self._do_close()
                raise

        self._page = (
            self._context.pages[0] if self._context.pages else self._context.new_page()
        )
        _safe_goto_ai(self._page)
        emit("已打开 Gemini 页面，请登录后使用「批量获取文案」。")

    def _do_batch(
        self,
        image_paths: list[str],
        prompt: str,
        on_progress: ProgressCallback | None,
    ) -> tuple[list[str], int, int, str | None]:
        def emit(line: str) -> None:
            if on_progress:
                on_progress(line)

        if not self._context_alive():
            emit("浏览器未打开或已关闭，正在重新打开…")
            self._do_open(on_progress)

        assert self._page is not None
        lines: list[str] = []
        documents: list[str] = []
        ok = fail = 0
        for path in image_paths:
            name = os.path.basename(path)
            try:
                parsed = process_one_image(self._page, path, prompt)
                documents.append(format_copy_document(parsed))
                ok += 1
                line = f"{name} - 已解析"
                lines.append(line)
                emit(line)
            except TimeoutError:
                fail += 1
                line = f"{name} - 超时未生成"
                lines.append(line)
                emit(line)
            except Exception as e:
                fail += 1
                line = f"{name} - 错误: {e}"
                lines.append(line)
                emit(line)

        dest: str | None = None
        if documents:
            dest = batch_txt_path(image_paths)
            write_batch_copy_txt(dest, documents)
            summary = f"已写入 {os.path.basename(dest)}（{len(documents)} 条）→ {dest}"
            lines.append(summary)
            emit(summary)
        else:
            msg = "无成功文案可保存"
            lines.append(msg)
            emit(msg)

        return lines, ok, fail, dest

    def _do_close(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
        self._context = None
        self._page = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._playwright = None


# 模块级会话，供 UI 复用
_default_session: GeminiBrowserSession | None = None


def get_gemini_session() -> GeminiBrowserSession:
    global _default_session
    if _default_session is None:
        _default_session = GeminiBrowserSession()
    return _default_session
