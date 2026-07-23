import os
import unittest

from tabs.common import upload_pairs


def _names(groups: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
    return [
        tuple(os.path.basename(path) for path in group)
        for group in groups
    ]


class UploadPairsTests(unittest.TestCase):
    def test_pairs_by_matching_number_instead_of_lexical_order(self) -> None:
        paths = [
            r"C:\images\1-1.jpg",
            r"C:\images\1.jpg",
            r"C:\images\10-10.jpg",
            r"C:\images\10.jpg",
            r"C:\images\2-2.jpg",
            r"C:\images\2.jpg",
        ]

        result = upload_pairs(paths)

        self.assertIsInstance(result, list)
        self.assertEqual(
            _names(result),
            [
                ("1.jpg", "1-1.jpg"),
                ("2.jpg", "2-2.jpg"),
                ("10.jpg", "10-10.jpg"),
            ],
        )

    def test_rejects_missing_and_orphaned_numbered_images(self) -> None:
        result = upload_pairs(
            [
                r"C:\images\1.jpg",
                r"C:\images\1-1.jpg",
                r"C:\images\2.jpg",
                r"C:\images\3-3.jpg",
            ]
        )

        self.assertIsInstance(result, str)
        self.assertIn("缺少副图 2-2", result)
        self.assertIn("缺少主图 3", result)

    def test_rejects_non_numbered_secondary_image(self) -> None:
        result = upload_pairs(
            [r"C:\images\1.jpg", r"C:\images\cover.jpg"]
        )

        self.assertIsInstance(result, str)
        self.assertIn("cover.jpg", result)
        self.assertIn("N-N", result)

    def test_keeps_legacy_sequential_pairing_without_main_images(self) -> None:
        paths = [
            r"C:\images\a.jpg",
            r"C:\images\b.jpg",
            r"C:\images\c.jpg",
        ]

        result = upload_pairs(paths)

        self.assertEqual(
            _names(result),
            [("a.jpg", "b.jpg"), ("c.jpg",)],
        )


if __name__ == "__main__":
    unittest.main()
