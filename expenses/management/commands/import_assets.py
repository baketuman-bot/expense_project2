"""
python manage.py import_assets [TSVファイルパス]

Accessシステムの v_assets エクスポートTSV（cp932）を T_ASSETS テーブルに一括登録。
TSVのヘッダー行はスキップし、Access クエリの SELECT 列順序でマッピングする。
既存レコードは上書き（upsert）、新規は追加。
"""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import make_aware, is_aware

from expenses.models import T_Assets


# ── 型変換ヘルパー ────────────────────────────────────────────────────────

def to_str(v):
    """空文字 / 空白 → None、それ以外はそのまま返す"""
    v = v.strip()
    return v if v else None


def to_int(v):
    v = v.strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def to_decimal(v):
    v = v.strip()
    if not v:
        return None
    try:
        return Decimal(v)
    except InvalidOperation:
        return None


def to_bit(v):
    """FALSE→0, TRUE→1, 空→None、それ以外は整数変換"""
    v = v.strip().upper()
    if v == 'TRUE':
        return 1
    if v == 'FALSE':
        return 0
    if not v:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


DATE_FMTS = ('%Y/%m/%d %H:%M', '%Y/%m/%d %H:%M:%S', '%Y/%m/%d')

def to_datetime(v):
    """日付文字列を aware datetime に変換（タイムゾーン対応）"""
    v = v.strip()
    if not v:
        return None
    for fmt in DATE_FMTS:
        try:
            dt = datetime.strptime(v, fmt)
            if not is_aware(dt):
                dt = make_aware(dt)
            return dt
        except ValueError:
            continue
    return None  # パース失敗時は None


# ── Access v_assets クエリの SELECT 列順序 ───────────────────────────────
# SELECT 句の並び順（左から 0 始まり）に対応するフィールド名と変換関数。
# TSV のヘッダー行はモデルフィールド定義順であり、データの列順序と異なるため
# ヘッダーを無視してこのマッピングでデータを読み込む。
ACCESS_COLUMNS = [
    ('asset_no',                        to_str),      #  0: fa.資産NO
    ('account_cd',                      to_str),      #  1: fa.科目コード
    ('account_name',                    to_str),      #  2: ac.名称（科目名）
    ('bumon_cd',                        to_str),      #  3: fa.部門コード
    ('bumon_name',                      to_str),      #  4: bm.名称（部門名）
    ('accounting_bumon_cd',             to_str),      #  5: bm.会計用部門コード
    ('asset_name1',                     to_str),      #  6: fa.資産名１
    ('asset_name2',                     to_str),      #  7: fa.資産名２
    ('structure_cd',                    to_str),      #  8: fa.構造細目コード
    ('structure_name',                  to_str),      #  9: kz.構造名
    ('detail_name',                     to_str),      # 10: kz.細目名
    ('alloc_kbn',                       to_str),      # 11: fa.部門配賦区分
    ('alloc_rate_cd',                   to_str),      # 12: fa.配賦率コード
    ('quantity',                        to_int),      # 13: fa.個数
    ('unit',                            to_str),      # 14: fa.単位
    ('useful_life',                     to_decimal),  # 15: fa.耐用年数
    ('depreciation_start_date',         to_datetime), # 16: fa.償却開始日
    ('acquisition_date',                to_datetime), # 17: fa.取得日
    ('transfer_date',                   to_datetime), # 18: fa.異動増日付
    ('acquisition_amount',              to_decimal),  # 19: fa.取得価額
    ('beginning_amount',                to_decimal),  # 20: fa.期首価額
    ('beginning_depreciation_diff',     to_decimal),  # 21: fa.期首償却過不足額
    ('residual_amount',                 to_decimal),  # 22: fa.残存価額
    ('current_optional_depreciation',   to_decimal),  # 23: fa.当期任意償却額
    ('current_optional_kbn',            to_bit),      # 24: fa.当期任意償却区分（BIT）
    ('compression_reserve',             to_decimal),  # 25: fa.圧縮引当金
    ('beginning_adjustment',            to_decimal),  # 26: fa.期首価額調整額
    ('depreciation_limit',              to_decimal),  # 27: fa.償却可能限度額
    ('collateral_kbn',                  to_str),      # 28: fa.担保資産区分
    ('special_depreciation_kbn',        to_str),      # 29: fa.特別償却計算区分
    ('extra_depreciation_kbn',          to_str),      # 30: fa.割増償却計算区分
    ('location_cd',                     to_str),      # 31: fa.設置場所コード
    ('location_name',                   to_str),      # 32: pl.名称（設置場所名）
    ('city_cd',                         to_str),      # 33: pl.市区町村コード
    ('city_name',                       to_str),      # 34: ct.名称（市区町村名）
    ('tax_target_kbn',                  to_str),      # 35: fa.納税対象区分
    ('installation_date',               to_datetime), # 36: fa.設置日
    ('increase_reason',                 to_str),      # 37: fa.増加事由
    ('disposal_kbn',                    to_str),      # 38: fa.除却区分
    ('disposal_date',                   to_datetime), # 39: fa.除却日
    ('disposal_amount',                 to_decimal),  # 40: fa.処分価額
    ('special_depreciation_amount',     to_decimal),  # 41: fa.特別償却額
    ('extra_depreciation_amount',       to_decimal),  # 42: fa.割増償却額
    ('registration_date',               to_datetime), # 43: fa.固定登録日
    ('disposal_registration_date',      to_datetime), # 44: fa.除却登録日
    ('transfer_registration_date',      to_datetime), # 45: fa.異動登録日
    ('special_registration_date',       to_datetime), # 46: fa.特割登録日
    ('source_asset_no',                 to_str),      # 47: fa.異動元資産NO
    ('special_rate_input_kbn',          to_bit),      # 48: fa.特例率入力区分（BIT）
    ('special_rate_numerator',          to_int),      # 49: fa.特例率分子
    ('special_rate_denominator',        to_int),      # 50: fa.特例率分母
    ('decrease_kbn',                    to_str),      # 51: fa.減少区分
    ('supplier_cd',                     to_str),      # 52: fa.購入先コード
    ('partial_expansion_asset_cd',      to_str),      # 53: fa.一部増設元資産コード
    ('depreciation_stop_start_date',    to_datetime), # 54: fa.償却停止開始日
    ('depreciation_stop_end_date',      to_datetime), # 55: fa.償却停止終了日
    ('prev_year_book_amount',           to_decimal),  # 56: fa.前年申告帳簿価額
    ('prev_year_assessed_amount',       to_decimal),  # 57: fa.前年申告評価額
    ('switch_book_amount',              to_decimal),  # 58: fa.切換時帳簿価額
    ('post_switch_annual_depreciation', to_decimal),  # 59: fa.切換後年償却額
    ('straight_line_switch_date',       to_datetime), # 60: fa.定額切換日
    ('ringi_no',                        to_str),      # 61: fa.稟議NO
    ('manager',                         to_str),      # 62: fa.管理者
    ('memo1',                           to_str),      # 63: fa.メモ欄
    ('memo2',                           to_str),      # 64: fa.メモ欄2
    ('model_name',                      to_str),      # 65: fa.モデル
    ('serial_no',                       to_str),      # 66: fa.シリアルNO
    ('physical_inventory_result',       to_str),      # 67: fa.実地調査結果
]

EXPECTED_COLS = len(ACCESS_COLUMNS)


class Command(BaseCommand):
    help = 'v_assets エクスポートTSV（cp932）を T_ASSETS に upsert インポートします'

    def add_arguments(self, parser):
        parser.add_argument(
            'filepath',
            nargs='?',
            default='/mnt/c/Users/idc_user/Desktop/data.txt',
            help='インポートするTSVファイルパス（デフォルト: /mnt/c/Users/idc_user/Desktop/data.txt）',
        )
        parser.add_argument(
            '--encoding', default='cp932',
            help='ファイルエンコーディング（デフォルト: cp932）',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='DBへの書き込みを行わず件数確認のみ',
        )

    def handle(self, *args, **options):
        filepath = Path(options['filepath'])
        encoding = options['encoding']
        dry_run  = options['dry_run']

        if not filepath.exists():
            raise CommandError(f'ファイルが見つかりません: {filepath}')

        self.stdout.write(f'読み込み開始: {filepath}  (encoding={encoding})')

        all_rows = []
        skipped  = 0
        errors   = []

        with open(filepath, encoding=encoding, newline='') as f:
            reader = csv.reader(f, delimiter='\t')

            # 1行目はヘッダー（モデルフィールド定義順）なのでスキップ
            next(reader)

            for lineno, row in enumerate(reader, start=2):
                if len(row) < EXPECTED_COLS:
                    errors.append(f'行{lineno}: 列数不足 ({len(row)} < {EXPECTED_COLS})')
                    skipped += 1
                    continue

                kwargs = {}
                for idx, (field, conv) in enumerate(ACCESS_COLUMNS):
                    kwargs[field] = conv(row[idx])

                if not kwargs.get('asset_no'):
                    skipped += 1
                    continue

                all_rows.append(kwargs)

        self.stdout.write(f'読み込み完了: {len(all_rows)} 件  (スキップ: {skipped} 件)')

        if errors:
            for e in errors[:10]:
                self.stdout.write(self.style.WARNING(e))

        if dry_run:
            # 先頭3件のパース結果を表示して確認
            self.stdout.write('\n--- dry-run プレビュー（先頭3件） ---')
            for row in all_rows[:3]:
                self.stdout.write(
                    f"  asset_no={row['asset_no']}  "
                    f"asset_name1={row['asset_name1']}  "
                    f"acquisition_amount={row['acquisition_amount']}  "
                    f"acquisition_date={row['acquisition_date']}  "
                    f"tax_target_kbn={row['tax_target_kbn']}"
                )
            self.stdout.write(self.style.WARNING('\n--dry-run モード: DBへの書き込みはスキップします'))
            return

        created = updated = 0
        total   = len(all_rows)

        for i, kwargs in enumerate(all_rows, 1):
            asset_no = kwargs.pop('asset_no')
            _, is_created = T_Assets.objects.update_or_create(
                asset_no=asset_no,
                defaults=kwargs,
            )
            if is_created:
                created += 1
            else:
                updated += 1

            if i % 200 == 0:
                self.stdout.write(f'  処理中... {i}/{total} 件')

        self.stdout.write(self.style.SUCCESS(
            f'\n完了: 新規 {created} 件 / 更新 {updated} 件 / スキップ {skipped} 件'
        ))
