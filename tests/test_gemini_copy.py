import unittest

from gemini_copy import format_copy_document, parse_gemini_copy


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


if __name__ == "__main__":
    unittest.main()
