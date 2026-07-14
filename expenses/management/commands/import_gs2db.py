"""
python manage.py import_gs2db <csv_dir> [--dry-run]

deploy/gs2db_sync/extract_gs2db.py が生成したCSV群
(gs_ringi.csv / gs_usr.csv / gs_group.csv / gs_belong.csv / gs_position.csv)
を読み込み、GS_Ringi / GS_Usr / GS_Group / GS_Belong / GS_Position へ
upsert登録する（DELETE/TRUNCATEは行わない）。
"""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from expenses.models import GS_Belong, GS_Group, GS_Position, GS_Ringi, GS_Usr


def to_int(v):
    v = (v or '').strip()
    if not v:
        return None
    return int(v)


def to_str(v):
    v = (v or '').strip()
    return v if v else None


def to_datetime(v):
    v = (v or '').strip()
    if not v:
        return None
    dt = parse_datetime(v)
    if dt is None:
        raise ValueError(f'日時としてパースできません: {v!r}')
    return dt


# (モデル, CSVファイル名, PKフィールド名または一意条件フィールド名のタプル, フィールド変換マップ)
TABLE_SPECS = [
    (
        GS_Ringi, 'gs_ringi.csv', ('rng_sid',),
        {
            'rng_sid': to_int, 'rng_title': to_str, 'rng_makedate': to_datetime,
            'rng_applicate': to_int, 'rng_appldate': to_datetime, 'rng_status': to_int,
            'rng_compflg': to_int, 'rng_admcomment': to_str, 'rng_auid': to_int,
            'rng_adate': to_datetime, 'rng_euid': to_int, 'rng_edate': to_datetime,
            'rng_id': to_str, 'rtp_sid': to_int, 'rtp_ver': to_int, 'rct_ver': to_int,
        },
    ),
    (
        GS_Usr, 'gs_usr.csv', ('usr_sid',),
        {
            'usr_sid': to_int, 'usr_lgid': to_str, 'usr_jkbn': to_int,
            'usi_sei': to_str, 'usi_mei': to_str, 'usi_sei_kn': to_str, 'usi_mei_kn': to_str,
            'usi_syain_no': to_str, 'usi_syozoku': to_str, 'usi_yakusyoku': to_str,
            'pos_sid': to_int, 'usi_entrance_date': to_datetime,
        },
    ),
    (
        GS_Group, 'gs_group.csv', ('grp_sid',),
        {
            'grp_sid': to_int, 'grp_id': to_str, 'grp_name': to_str, 'grp_name_kn': to_str,
            'grp_comment': to_str, 'grp_auid': to_int, 'grp_adate': to_datetime,
            'grp_euid': to_int, 'grp_edate': to_datetime, 'grp_sort': to_int, 'grp_jkbn': to_int,
        },
    ),
    (
        GS_Belong, 'gs_belong.csv', ('grp_sid', 'usr_sid', 'beg_grpkbn'),
        {
            'grp_sid': to_int, 'usr_sid': to_int, 'beg_auid': to_int,
            'beg_adate': to_datetime, 'beg_euid': to_int, 'beg_edate': to_datetime,
            'beg_defgrp': to_int, 'beg_grpkbn': to_int,
        },
    ),
    (
        GS_Position, 'gs_position.csv', ('pos_sid',),
        {
            'pos_sid': to_int, 'pos_code': to_str, 'pos_name': to_str, 'pos_biko': to_str,
            'pos_sort': to_int, 'pos_auid': to_int, 'pos_adate': to_datetime,
            'pos_euid': to_int, 'pos_edate': to_datetime,
        },
    ),
]


class Command(BaseCommand):
    help = 'deploy/gs2db_sync/extract_gs2db.py が出力したCSVをGS_*テーブルへupsertインポートします'

    def add_arguments(self, parser):
        parser.add_argument('csv_dir', help='CSV出力ディレクトリ（gs_*.csvが入っている場所）')
        parser.add_argument('--dry-run', action='store_true', help='DBへの書き込みを行わず件数確認のみ')

    def handle(self, *args, **options):
        csv_dir = Path(options['csv_dir'])
        dry_run = options['dry_run']

        if not csv_dir.is_dir():
            raise CommandError(f'ディレクトリが見つかりません: {csv_dir}')

        for model, filename, key_fields, converters in TABLE_SPECS:
            path = csv_dir / filename
            if not path.exists():
                self.stdout.write(self.style.WARNING(f'スキップ（見つかりません）: {path}'))
                continue

            rows = []
            with open(path, encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                for raw_row in reader:
                    kwargs = {field: conv(raw_row.get(field)) for field, conv in converters.items()}
                    rows.append(kwargs)

            self.stdout.write(f'{filename}: {len(rows)} 件読み込み')

            if dry_run:
                for row in rows[:3]:
                    self.stdout.write(f'  {row}')
                continue

            created = updated = 0
            for kwargs in rows:
                lookup = {k: kwargs[k] for k in key_fields}
                _, is_created = model.objects.update_or_create(defaults=kwargs, **lookup)
                if is_created:
                    created += 1
                else:
                    updated += 1

            self.stdout.write(self.style.SUCCESS(
                f'{model._meta.db_table}: 新規 {created} 件 / 更新 {updated} 件'
            ))

        if dry_run:
            self.stdout.write(self.style.WARNING('--dry-run モード: DBへの書き込みはスキップしました'))
