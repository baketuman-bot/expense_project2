"""extract_gs2db のうち、Java/H2を必要としない純粋関数の単体テスト"""
import csv
import datetime
import tempfile
import unittest
from pathlib import Path

from extract_gs2db import merge_usr_rows, value_to_csv, write_csv
from h2recover_parser import UnresolvedLob


class ValueToCsvTest(unittest.TestCase):
    def test_none_becomes_empty_string(self):
        self.assertEqual(value_to_csv(None), '')

    def test_unresolved_lob_becomes_empty_string(self):
        self.assertEqual(value_to_csv(UnresolvedLob('READ_CLOB_DB(1,2)')), '')

    def test_datetime_isoformat(self):
        dt = datetime.datetime(2025, 6, 24, 16, 21, 28, 112000)
        self.assertEqual(value_to_csv(dt), '2025-06-24 16:21:28.112000')

    def test_int_and_str_passthrough(self):
        self.assertEqual(value_to_csv(17), '17')
        self.assertEqual(value_to_csv('経理部'), '経理部')


class WriteCsvTest(unittest.TestCase):
    def test_writes_header_and_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'out.csv'
            write_csv(path, ['a', 'b'], [{'a': 1, 'b': '経理部'}, {'a': 2, 'b': None}])
            with open(path, encoding='utf-8', newline='') as f:
                reader = csv.reader(f)
                rows = list(reader)
        self.assertEqual(rows[0], ['a', 'b'])
        self.assertEqual(rows[1], ['1', '経理部'])
        self.assertEqual(rows[2], ['2', ''])


class MergeUsrRowsTest(unittest.TestCase):
    def test_merges_by_usr_sid_and_excludes_password(self):
        usrm_rows = {
            100: {'usr_sid': 100, 'usr_lgid': 'taro', 'usr_jkbn': 1, 'usr_pswd': 'secrethash'},
        }
        inf_rows = {
            100: {'usr_sid': 100, 'usi_sei': '山田', 'usi_mei': '太郎', 'usi_syain_no': '001'},
        }
        merged = merge_usr_rows(usrm_rows, inf_rows)
        self.assertEqual(len(merged), 1)
        row = merged[0]
        self.assertEqual(row['usr_sid'], 100)
        self.assertEqual(row['usr_lgid'], 'taro')
        self.assertEqual(row['usi_sei'], '山田')
        self.assertNotIn('usr_pswd', row)

    def test_missing_inf_row_leaves_profile_fields_none(self):
        usrm_rows = {200: {'usr_sid': 200, 'usr_lgid': 'jiro', 'usr_jkbn': 1}}
        inf_rows = {}
        merged = merge_usr_rows(usrm_rows, inf_rows)
        self.assertEqual(merged[0]['usr_sid'], 200)
        self.assertIsNone(merged[0]['usi_sei'])


if __name__ == '__main__':
    unittest.main()
