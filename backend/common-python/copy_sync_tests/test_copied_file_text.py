import unittest

from copy_sync_tests.copied_file_text import (
    normalize_copied_body,
    parse_origin_comment,
    strip_import_lines,
)


class TestCopiedFileTextHelpers(unittest.TestCase):
    def test_origin_comment_and_following_blank_line_are_stripped(self):
        text = (
            '# Copied from backend/cosmetology-app/lambdas/python/common/cc_common/utils.py\n'
            '\n'
            'from cc_common.config import config\n'
            '\n'
            'VALUE = 1\n'
        )
        parsed = parse_origin_comment(text)
        self.assertIsNotNone(parsed)
        kind, source, remainder = parsed
        self.assertEqual(kind, 'whole_file')
        self.assertEqual(source, 'backend/cosmetology-app/lambdas/python/common/cc_common/utils.py')
        self.assertEqual(remainder, 'from cc_common.config import config\n\nVALUE = 1\n')

    def test_method_body_origin_is_not_a_whole_file_copy(self):
        text = (
            '# Copied method bodies from backend/compact-connect/lambdas/python/common/cc_common/event_bus_client.py\n'
            '\n'
            'class Mixin:\n'
            '    pass\n'
        )
        kind, source, _remainder = parse_origin_comment(text)
        self.assertEqual(kind, 'method_bodies')
        self.assertTrue(source.endswith('event_bus_client.py'))

    def test_common_lambdas_import_rewrite_is_reversed(self):
        body = 'from common_lambdas.config import config\nfrom common_lambdas.utils import api_handler\n'
        self.assertEqual(
            normalize_copied_body(body),
            'from cc_common.config import config\nfrom cc_common.utils import api_handler\n',
        )

    def test_import_lines_including_parenthesized_blocks_are_removed(self):
        text = 'from pathlib import Path\nfrom foo import (\n    a,\n    b,\n)\nimport os\n\nVALUE = Path(__file__)\n'
        self.assertEqual(strip_import_lines(text).strip(), 'VALUE = Path(__file__)')

    def test_mid_file_import_does_not_leave_extra_blank_lines(self):
        text = 'class A:\n    pass\n\nfrom foo import bar\n\nclass B:\n    pass\n'
        self.assertEqual(
            strip_import_lines(text),
            'class A:\n    pass\n\nclass B:\n    pass\n',
        )
