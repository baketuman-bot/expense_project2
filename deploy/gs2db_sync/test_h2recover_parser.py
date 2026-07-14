"""h2recover_parser の単体テスト（外部依存なし、Java/H2不要）"""
import datetime
import unittest

from h2recover_parser import (
    UnresolvedLob, parse_scalar, parse_values_tuple, split_top_level, stringdecode,
)


class StringdecodeTest(unittest.TestCase):
    def test_basic_escapes(self):
        self.assertEqual(stringdecode(r'a\nb'), 'a\nb')
        self.assertEqual(stringdecode(r'a\tb'), 'a\tb')
        self.assertEqual(stringdecode(r'a\\b'), 'a\\b')

    def test_unicode_escape(self):
        self.assertEqual(stringdecode(r'与信'), '与信')

    def test_no_escapes_passthrough(self):
        self.assertEqual(stringdecode('plain text'), 'plain text')


class SplitTopLevelTest(unittest.TestCase):
    def test_simple_comma_split(self):
        self.assertEqual(split_top_level('1, 2, 3'), ['1', '2', '3'])

    def test_paren_depth_not_split(self):
        self.assertEqual(
            split_top_level("1, READ_CLOB_DB(41, 9901), 3"),
            ['1', 'READ_CLOB_DB(41, 9901)', '3'],
        )

    def test_comma_inside_quotes_not_split(self):
        self.assertEqual(
            split_top_level("1, 'a,b,c', 3"),
            ['1', "'a,b,c'", '3'],
        )

    def test_escaped_quote_inside_string(self):
        self.assertEqual(
            split_top_level("1, 'it''s, ok', 3"),
            ['1', "'it''s, ok'", '3'],
        )


class ParseScalarTest(unittest.TestCase):
    def test_null(self):
        self.assertIsNone(parse_scalar('NULL'))

    def test_integer(self):
        self.assertEqual(parse_scalar('344'), 344)
        self.assertEqual(parse_scalar('-1'), -1)

    def test_plain_quoted_string(self):
        self.assertEqual(parse_scalar("'G001'"), 'G001')

    def test_stringdecode_with_japanese_and_escape(self):
        self.assertEqual(
            parse_scalar(r"STRINGDECODE('与信管理申請(作成中)')"),
            '与信管理申請(作成中)',
        )

    def test_timestamp(self):
        self.assertEqual(
            parse_scalar("TIMESTAMP '2025-06-24 16:21:28.112'"),
            datetime.datetime(2025, 6, 24, 16, 21, 28, 112000),
        )

    def test_timestamp_without_fraction(self):
        self.assertEqual(
            parse_scalar("TIMESTAMP '2025-06-24 16:21:28'"),
            datetime.datetime(2025, 6, 24, 16, 21, 28),
        )

    def test_unresolved_lob_function_call(self):
        result = parse_scalar('READ_CLOB_DB(41, 9901)')
        self.assertIsInstance(result, UnresolvedLob)
        self.assertEqual(result.raw, 'READ_CLOB_DB(41, 9901)')


class ParseValuesTupleTest(unittest.TestCase):
    def test_mixed_row(self):
        result = parse_values_tuple(
            "17, 1, 0, STRINGDECODE('\\u4e0e\\u4fe1'), NULL, TIMESTAMP '2025-06-24 16:21:28.112'"
        )
        self.assertEqual(result[0], 17)
        self.assertEqual(result[1], 1)
        self.assertEqual(result[2], 0)
        self.assertEqual(result[3], '与信')
        self.assertIsNone(result[4])
        self.assertEqual(result[5], datetime.datetime(2025, 6, 24, 16, 21, 28, 112000))


if __name__ == '__main__':
    unittest.main()
