"""import_gs2db 管理コマンドのテスト"""
import csv
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from expenses.models import GS_Belong, GS_Group, GS_Ringi, GS_Usr


class ImportGs2dbTest(TestCase):
    def _write_csv(self, dir_path, filename, header, rows):
        path = Path(dir_path) / filename
        with open(path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for row in rows:
                writer.writerow(row)
        return path

    def test_import_creates_gs_ringi_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_csv(
                tmp_dir, 'gs_ringi.csv',
                ['rng_sid', 'rng_title', 'rng_makedate', 'rng_applicate', 'rng_appldate',
                 'rng_status', 'rng_compflg', 'rng_admcomment', 'rng_auid', 'rng_adate',
                 'rng_euid', 'rng_edate', 'rng_id', 'rtp_sid', 'rtp_ver', 'rct_ver'],
                [['17', '与信管理申請(作成中)', '2025-06-24 16:21:28.112', '344', '',
                  '1', '0', '', '594', '2025-08-24 13:36:00.786',
                  '6', '2025-08-24 13:36:00.786', '', '41', '1', '0']],
            )
            self._write_csv(
                tmp_dir, 'gs_group.csv',
                ['grp_sid', 'grp_id', 'grp_name', 'grp_name_kn', 'grp_comment',
                 'grp_auid', 'grp_adate', 'grp_euid', 'grp_edate', 'grp_sort', 'grp_jkbn'],
                [['1', 'G001', '経理部', 'ケイリブ', '',
                  '1', '2025-01-01 00:00:00', '1', '2025-01-01 00:00:00', '1', '1']],
            )

            call_command('import_gs2db', tmp_dir)

            ringi = GS_Ringi.objects.get(rng_sid=17)
            self.assertEqual(ringi.rng_title, '与信管理申請(作成中)')
            self.assertEqual(ringi.rng_applicate, 344)
            self.assertIsNone(ringi.rng_appldate)

            grp = GS_Group.objects.get(grp_sid=1)
            self.assertEqual(grp.grp_name, '経理部')

    def test_import_is_idempotent_upsert(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            header = ['grp_sid', 'grp_id', 'grp_name', 'grp_name_kn', 'grp_comment',
                       'grp_auid', 'grp_adate', 'grp_euid', 'grp_edate', 'grp_sort', 'grp_jkbn']
            self._write_csv(tmp_dir, 'gs_group.csv', header,
                             [['1', 'G001', '経理部', '', '', '1', '2025-01-01 00:00:00',
                               '1', '2025-01-01 00:00:00', '1', '1']])
            call_command('import_gs2db', tmp_dir)
            self._write_csv(tmp_dir, 'gs_group.csv', header,
                             [['1', 'G001', '経理部(改称)', '', '', '1', '2025-01-01 00:00:00',
                               '1', '2025-01-02 00:00:00', '1', '1']])
            call_command('import_gs2db', tmp_dir)

            self.assertEqual(GS_Group.objects.count(), 1)
            self.assertEqual(GS_Group.objects.get(grp_sid=1).grp_name, '経理部(改称)')

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_csv(
                tmp_dir, 'gs_position.csv',
                ['pos_sid', 'pos_code', 'pos_name', 'pos_biko', 'pos_sort',
                 'pos_auid', 'pos_adate', 'pos_euid', 'pos_edate'],
                [['1', 'P01', '課長', '', '1', '1', '2025-01-01 00:00:00', '1', '2025-01-01 00:00:00']],
            )
            call_command('import_gs2db', tmp_dir, '--dry-run')
            from expenses.models import GS_Position
            self.assertEqual(GS_Position.objects.count(), 0)

    def test_import_gs2db_belong_composite_key_upsert(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            header = ['grp_sid', 'usr_sid', 'beg_auid', 'beg_adate', 'beg_euid', 'beg_edate',
                      'beg_defgrp', 'beg_grpkbn']
            self._write_csv(tmp_dir, 'gs_belong.csv', header,
                             [['1', '100', '1', '2025-01-01 00:00:00',
                               '1', '2025-01-01 00:00:00', '1', '0']])

            call_command('import_gs2db', tmp_dir)

            self.assertEqual(GS_Belong.objects.count(), 1)
            belong = GS_Belong.objects.get(grp_sid=1, usr_sid=100, beg_grpkbn=0)
            self.assertEqual(belong.beg_auid, 1)
            self.assertEqual(belong.beg_defgrp, 1)

            # 同じCSVを再インポートしても複製が作られない（冪等性）
            call_command('import_gs2db', tmp_dir)
            self.assertEqual(GS_Belong.objects.count(), 1)

    def test_import_gs2db_usr(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_csv(
                tmp_dir, 'gs_usr.csv',
                ['usr_sid', 'usr_lgid', 'usr_jkbn', 'usi_sei', 'usi_mei', 'usi_sei_kn',
                 'usi_mei_kn', 'usi_syain_no', 'usi_syozoku', 'usi_yakusyoku', 'pos_sid',
                 'usi_entrance_date'],
                [['100', 'taro', '1', '山田', '太郎', 'ヤマダ', 'タロウ', '001',
                  '経理部', '課長', '1', '2020-04-01 00:00:00']],
            )

            call_command('import_gs2db', tmp_dir)

            usr = GS_Usr.objects.get(usr_sid=100)
            self.assertEqual(usr.usr_lgid, 'taro')
            self.assertEqual(usr.usr_jkbn, 1)
            self.assertEqual(usr.usi_sei, '山田')
            self.assertEqual(usr.usi_mei, '太郎')
            self.assertEqual(usr.usi_syain_no, '001')
            self.assertEqual(usr.pos_sid, 1)
