import sys
import unittest
import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import sync_assets as sa


class RestorePayloadValueTest(unittest.TestCase):
    def test_restores_date_string_to_datetime(self):
        result = sa.restore_payload_value('acquisition_date', '2026-07-01 00:00:00')
        self.assertEqual(result, datetime.datetime(2026, 7, 1, 0, 0, 0))

    def test_restores_decimal_string_to_decimal(self):
        result = sa.restore_payload_value('acquisition_amount', '1234567.5000')
        self.assertEqual(result, Decimal('1234567.5000'))

    def test_passes_through_plain_string_field(self):
        result = sa.restore_payload_value('asset_name1', 'テスト資産')
        self.assertEqual(result, 'テスト資産')

    def test_none_stays_none(self):
        self.assertIsNone(sa.restore_payload_value('acquisition_amount', None))


class PullValueToMysqlTest(unittest.TestCase):
    def test_normalizes_float_to_decimal_for_amount_field(self):
        result = sa.pull_value_to_mysql('acquisition_amount', 1234567.5)
        self.assertEqual(result, Decimal('1234567.5'))

    def test_passes_through_string_field(self):
        result = sa.pull_value_to_mysql('asset_name1', 'テスト資産')
        self.assertEqual(result, 'テスト資産')


class FieldMappingTest(unittest.TestCase):
    def test_field_to_access_column_has_60_entries(self):
        self.assertEqual(len(sa.FIELD_TO_ACCESS_COLUMN), 60)

    def test_readonly_master_fields_excluded_from_push_mapping(self):
        readonly = {
            'account_name', 'bumon_name', 'accounting_bumon_cd', 'structure_name',
            'detail_name', 'location_name', 'city_cd', 'city_name',
        }
        self.assertFalse(readonly & set(sa.FIELD_TO_ACCESS_COLUMN))

    def test_pull_columns_has_68_entries(self):
        self.assertEqual(len(sa.PULL_COLUMNS), 68)


if __name__ == '__main__':
    unittest.main()
