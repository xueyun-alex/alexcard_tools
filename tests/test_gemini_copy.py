import unittest
from unittest import mock

from gemini_copy import (
    FORMAT_REPAIR_PROMPT,
    _extract_reply_text,
    build_generation_prompt,
    format_copy_document,
    parse_gemini_copy,
    process_one_image,
)


class GeminiCopyParsingTests(unittest.TestCase):
    def test_ignores_preamble_and_content_below_separator(self) -> None:
        parsed = parse_gemini_copy(
            "好的，下面是生成结果：\n"
            "这段文字不应保存\n"
            "【标题】测试标题\n"
            "【宝贝描述】第一段描述\n第二段描述\n"
            "【标签】#标签一 #标签二\n"
            "────────\n"
            "分隔线以下的推荐内容不应保存"
        )

        self.assertEqual(parsed.title, "测试标题")
        self.assertEqual(parsed.description, "第一段描述\n第二段描述")
        self.assertEqual(parsed.tags, "#标签一 #标签二")

    def test_recovers_title_when_title_marker_is_missing(self) -> None:
        parsed = parse_gemini_copy(
            "以下是生成的闲鱼文案\n"
            "恢复出来的商品标题\n"
            "【宝贝描述】商品描述内容\n"
            "【标签】#标签一 #标签二"
        )

        self.assertEqual(parsed.title, "恢复出来的商品标题")
        self.assertEqual(parsed.description, "商品描述内容")
        self.assertEqual(parsed.tags, "#标签一 #标签二")

    def test_does_not_mistake_description_marker_for_missing_title(self) -> None:
        with self.assertRaisesRegex(ValueError, "【标题】"):
            parse_gemini_copy(
                "【宝贝描述】只有描述，没有任何标题内容\n"
                "【标签】#标签一 #标签二"
            )

    def test_recovers_inline_title_after_preamble(self) -> None:
        parsed = parse_gemini_copy(
            "以下是文案：同一行中的商品标题\n"
            "【宝贝描述】商品描述内容\n"
            "【标签】#标签一"
        )

        self.assertEqual(parsed.title, "同一行中的商品标题")

    def test_stops_tags_at_first_non_tag_footer_line(self) -> None:
        parsed = parse_gemini_copy(
            "【标题】测试标题\n"
            "【宝贝描述】测试描述\n"
            "【标签】#标签一\n#标签二\n"
            "AI 生成内容仅供参考\n"
            "更多无关文字"
        )

        self.assertEqual(parsed.tags, "#标签一\n#标签二")

    def test_formatted_document_always_has_three_sections(self) -> None:
        parsed = parse_gemini_copy(
            "没有标题标记的标题\n"
            "【宝贝描述】测试描述\n"
            "【标签】#测试标签"
        )

        document = format_copy_document(parsed)

        self.assertEqual(document.count("【标题】"), 1)
        self.assertEqual(document.count("【宝贝描述】"), 1)
        self.assertEqual(document.count("【标签】"), 1)
        self.assertTrue(document.rstrip().endswith("#测试标签"))

    def test_accepts_plain_colon_field_names(self) -> None:
        parsed = parse_gemini_copy(
            "商品标题：普通字段标题\n"
            "商品描述：普通字段描述\n第二段描述\n"
            "关键词：球星卡、桌面摆件"
        )

        self.assertEqual(parsed.title, "普通字段标题")
        self.assertEqual(parsed.description, "普通字段描述\n第二段描述")
        self.assertEqual(parsed.tags, "球星卡、桌面摆件")

    def test_accepts_markdown_headings_and_aliases(self) -> None:
        parsed = parse_gemini_copy(
            "### 宝贝标题\nMarkdown 标题\n"
            "### 商品文案\nMarkdown 描述\n"
            "### 话题标签\n#标签一 #标签二"
        )

        self.assertEqual(parsed.title, "Markdown 标题")
        self.assertEqual(parsed.description, "Markdown 描述")
        self.assertEqual(parsed.tags, "#标签一 #标签二")

    def test_accepts_numbered_english_fields(self) -> None:
        parsed = parse_gemini_copy(
            "1. Title: English title\n"
            "2. Description: English description\n"
            "3. Tags: #tag-one #tag-two"
        )

        self.assertEqual(parsed.title, "English title")
        self.assertEqual(parsed.description, "English description")
        self.assertEqual(parsed.tags, "#tag-one #tag-two")

    def test_accepts_plain_fields_on_one_line(self) -> None:
        parsed = parse_gemini_copy(
            "标题：单行标题 宝贝描述：单行描述 标签：#单行标签"
        )

        self.assertEqual(parsed.title, "单行标题")
        self.assertEqual(parsed.description, "单行描述")
        self.assertEqual(parsed.tags, "#单行标签")

    def test_accepts_json_and_tag_array(self) -> None:
        parsed = parse_gemini_copy(
            '{"title":"JSON 标题","description":"JSON 描述",'
            '"tags":["#标签一","#标签二"]}'
        )

        self.assertEqual(parsed.title, "JSON 标题")
        self.assertEqual(parsed.description, "JSON 描述")
        self.assertEqual(parsed.tags, "#标签一 #标签二")

    def test_recovers_missing_title_with_nonstandard_description_marker(self) -> None:
        parsed = parse_gemini_copy(
            "好的，以下是文案\n"
            "缺少字段名的真实标题\n"
            "商品描述：商品描述内容\n"
            "Tags: #标签一 #标签二"
        )

        self.assertEqual(parsed.title, "缺少字段名的真实标题")
        self.assertEqual(parsed.description, "商品描述内容")

    def test_recovers_completely_unlabeled_reply(self) -> None:
        parsed = parse_gemini_copy(
            "好的，下面是结果\n"
            "无字段商品标题\n"
            "第一段商品描述\n"
            "第二段商品描述\n"
            "#标签一 #标签二"
        )

        self.assertEqual(parsed.title, "无字段商品标题")
        self.assertEqual(
            parsed.description,
            "第一段商品描述\n第二段商品描述",
        )
        self.assertEqual(parsed.tags, "#标签一 #标签二")

    def test_generation_prompt_always_appends_output_contract(self) -> None:
        prompt = build_generation_prompt("用户自定义提示词")

        self.assertTrue(prompt.startswith("用户自定义提示词"))
        self.assertIn("【标题】", prompt)
        self.assertIn("【宝贝描述】", prompt)
        self.assertIn("【标签】", prompt)
        self.assertIn("三个区段都不能为空", prompt)

    def test_process_retries_once_with_format_repair_prompt(self) -> None:
        repaired = (
            "【标题】修复标题\n"
            "【宝贝描述】修复描述\n"
            "【标签】#修复标签"
        )
        with (
            mock.patch("gemini_copy._ensure_on_chat"),
            mock.patch("gemini_copy._extract_aimc_text", return_value=""),
            mock.patch("gemini_copy._copy_image_to_clipboard"),
            mock.patch("gemini_copy._paste_image_from_clipboard"),
            mock.patch("gemini_copy._wait_send_ready"),
            mock.patch("gemini_copy._click_send") as click_send,
            mock.patch("gemini_copy._fill_prompt") as fill_prompt,
            mock.patch(
                "gemini_copy._wait_for_copy_ready",
                side_effect=["无法解析的单行回复", repaired],
            ),
        ):
            parsed = process_one_image(object(), "1.png", "自定义提示词")

        self.assertEqual(parsed.title, "修复标题")
        self.assertEqual(click_send.call_count, 2)
        self.assertIn("【标题】", fill_prompt.call_args_list[0].args[1])
        self.assertEqual(fill_prompt.call_args_list[1].args[1], FORMAT_REPAIR_PROMPT)

    def test_reply_block_wins_over_prompt_markers_in_page_body(self) -> None:
        page = mock.Mock()
        with mock.patch(
            "gemini_copy._extract_aimc_text",
            return_value="标题：其他格式标题\n描述：描述内容\n标签：#标签",
        ):
            reply = _extract_reply_text(page)

        self.assertTrue(reply.startswith("标题：其他格式标题"))
        page.locator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
