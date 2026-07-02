"""
固定資産台帳 Access MDB 双方向同期スクリプト（Windows専用・Django非依存）

使い方:
    python sync_assets.py [--config config.ini] [--dry-run] [--retry-errors]

処理フロー:
    1. 接続確認（MDB / MySQL）
    2. Pushキューが1件でもあれば書き込み前にMDBをバックアップ
    3. Push: MySQL の T_AssetsSyncQueue(pending, --retry-errors 指定時は error も) を
       本物MDB tbl固定資産へ UPDATE/INSERT
    4. Pull: 本物MDB v_assets を MySQL T_ASSETS へ upsert
       （pending/error のキューが残っている資産NOはスキップ）
"""
import argparse
import configparser
import datetime
import json
import logging
import shutil
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

LOG_PATH = Path(__file__).with_name('sync_assets.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger('sync_assets')


# ── フィールド名 → Access列名マッピング（expenses/management/commands/import_assets.py の
#    ACCESS_COLUMNS コメント由来）。Push対象は tbl固定資産(fa.*) 実列の60項目のみ。
#    マスタ結合由来の8項目（account_name/bumon_name/accounting_bumon_cd/structure_name/
#    detail_name/location_name/city_cd/city_name）はPush対象外。
FIELD_TO_ACCESS_COLUMN = {
    'asset_no': '資産NO',
    'account_cd': '科目コード',
    'bumon_cd': '部門コード',
    'asset_name1': '資産名１',
    'asset_name2': '資産名２',
    'structure_cd': '構造細目コード',
    'alloc_kbn': '部門配賦区分',
    'alloc_rate_cd': '配賦率コード',
    'quantity': '個数',
    'unit': '単位',
    'useful_life': '耐用年数',
    'depreciation_start_date': '償却開始日',
    'acquisition_date': '取得日',
    'transfer_date': '異動増日付',
    'acquisition_amount': '取得価額',
    'beginning_amount': '期首価額',
    'beginning_depreciation_diff': '期首償却過不足額',
    'residual_amount': '残存価額',
    'current_optional_depreciation': '当期任意償却額',
    'current_optional_kbn': '当期任意償却区分',
    'compression_reserve': '圧縮引当金',
    'beginning_adjustment': '期首価額調整額',
    'depreciation_limit': '償却可能限度額',
    'collateral_kbn': '担保資産区分',
    'special_depreciation_kbn': '特別償却計算区分',
    'extra_depreciation_kbn': '割増償却計算区分',
    'location_cd': '設置場所コード',
    'tax_target_kbn': '納税対象区分',
    'installation_date': '設置日',
    'increase_reason': '増加事由',
    'disposal_kbn': '除却区分',
    'disposal_date': '除却日',
    'disposal_amount': '処分価額',
    'special_depreciation_amount': '特別償却額',
    'extra_depreciation_amount': '割増償却額',
    'registration_date': '固定登録日',
    'disposal_registration_date': '除却登録日',
    'transfer_registration_date': '異動登録日',
    'special_registration_date': '特割登録日',
    'source_asset_no': '異動元資産NO',
    'special_rate_input_kbn': '特例率入力区分',
    'special_rate_numerator': '特例率分子',
    'special_rate_denominator': '特例率分母',
    'decrease_kbn': '減少区分',
    'supplier_cd': '購入先コード',
    'partial_expansion_asset_cd': '一部増設元資産コード',
    'depreciation_stop_start_date': '償却停止開始日',
    'depreciation_stop_end_date': '償却停止終了日',
    'prev_year_book_amount': '前年申告帳簿価額',
    'prev_year_assessed_amount': '前年申告評価額',
    'switch_book_amount': '切換時帳簿価額',
    'post_switch_annual_depreciation': '切換後年償却額',
    'straight_line_switch_date': '定額切換日',
    'ringi_no': '稟議NO',
    'manager': '管理者',
    'memo1': 'メモ欄',
    'memo2': 'メモ欄2',
    'model_name': 'モデル',
    'serial_no': 'シリアルNO',
    'physical_inventory_result': '実地調査結果',
}

# ── v_assets SELECT列順序 → T_ASSETSフィールド名（Pull用。import_assets.py の
#    ACCESS_COLUMNS と同順、68列） ──
PULL_COLUMNS = [
    'asset_no', 'account_cd', 'account_name', 'bumon_cd', 'bumon_name', 'accounting_bumon_cd',
    'asset_name1', 'asset_name2', 'structure_cd', 'structure_name', 'detail_name',
    'alloc_kbn', 'alloc_rate_cd', 'quantity', 'unit', 'useful_life',
    'depreciation_start_date', 'acquisition_date', 'transfer_date',
    'acquisition_amount', 'beginning_amount', 'beginning_depreciation_diff', 'residual_amount',
    'current_optional_depreciation', 'current_optional_kbn', 'compression_reserve',
    'beginning_adjustment', 'depreciation_limit', 'collateral_kbn', 'special_depreciation_kbn',
    'extra_depreciation_kbn', 'location_cd', 'location_name', 'city_cd', 'city_name',
    'tax_target_kbn', 'installation_date', 'increase_reason', 'disposal_kbn', 'disposal_date',
    'disposal_amount', 'special_depreciation_amount', 'extra_depreciation_amount',
    'registration_date', 'disposal_registration_date', 'transfer_registration_date',
    'special_registration_date', 'source_asset_no', 'special_rate_input_kbn',
    'special_rate_numerator', 'special_rate_denominator', 'decrease_kbn', 'supplier_cd',
    'partial_expansion_asset_cd', 'depreciation_stop_start_date', 'depreciation_stop_end_date',
    'prev_year_book_amount', 'prev_year_assessed_amount', 'switch_book_amount',
    'post_switch_annual_depreciation', 'straight_line_switch_date', 'ringi_no', 'manager',
    'memo1', 'memo2', 'model_name', 'serial_no', 'physical_inventory_result',
]

DECIMAL_FIELDS = {
    'useful_life', 'acquisition_amount', 'beginning_amount', 'beginning_depreciation_diff',
    'residual_amount', 'current_optional_depreciation', 'compression_reserve',
    'beginning_adjustment', 'depreciation_limit', 'disposal_amount',
    'special_depreciation_amount', 'extra_depreciation_amount', 'prev_year_book_amount',
    'prev_year_assessed_amount', 'switch_book_amount', 'post_switch_annual_depreciation',
}

DATE_FIELDS = {
    'depreciation_start_date', 'acquisition_date', 'transfer_date', 'installation_date',
    'disposal_date', 'registration_date', 'disposal_registration_date',
    'transfer_registration_date', 'special_registration_date',
    'depreciation_stop_start_date', 'depreciation_stop_end_date', 'straight_line_switch_date',
}


def load_config(path):
    cfg = configparser.ConfigParser()
    read_files = cfg.read(path, encoding='utf-8')
    if not read_files:
        raise SystemExit(f'設定ファイルが見つかりません: {path}')
    return cfg


def restore_payload_value(field_name, value):
    """T_AssetsSyncQueue.payload のJSON値をAccess書き込み用のPython値に復元する。"""
    if value is None:
        return None
    if field_name in DATE_FIELDS:
        return datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    if field_name in DECIMAL_FIELDS:
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    return value


def pull_value_to_mysql(field_name, value):
    """pyodbcが返すAccessの値をMySQL upsert用に正規化する。"""
    if value is None:
        return None
    if field_name in DECIMAL_FIELDS and not isinstance(value, Decimal):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    return value


def connect_mdb(cfg):
    import pyodbc
    mdb_path = cfg['mdb']['path']
    password = cfg['mdb'].get('password', '').strip()
    conn_str = f'Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={mdb_path};'
    if password:
        conn_str += f'PWD={password};'
    return pyodbc.connect(conn_str, autocommit=False)


def connect_mysql(cfg):
    import MySQLdb
    return MySQLdb.connect(
        host=cfg['mysql']['host'],
        port=cfg['mysql'].getint('port', fallback=3306),
        user=cfg['mysql']['user'],
        passwd=cfg['mysql']['password'],
        db=cfg['mysql']['database'],
        charset='utf8mb4',
    )


def backup_mdb(cfg):
    """書き込み前にMDBをタイムスタンプ付きでバックアップし、古い世代を削除する。"""
    mdb_path = Path(cfg['mdb']['path'])
    backup_dir = Path(cfg['backup']['dir'])
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = backup_dir / f'{mdb_path.stem}_{timestamp}{mdb_path.suffix}'
    shutil.copy2(mdb_path, backup_path)
    logger.info('MDBバックアップ作成: %s', backup_path)

    keep = cfg['backup'].getint('keep', fallback=10)
    backups = sorted(backup_dir.glob(f'{mdb_path.stem}_*{mdb_path.suffix}'))
    for old in backups[:-keep] if keep > 0 else []:
        old.unlink()
        logger.info('古いバックアップを削除: %s', old)
    return backup_path


def fetch_push_queue(mysql_conn, retry_errors):
    statuses = ('pending', 'error') if retry_errors else ('pending',)
    placeholders = ','.join(['%s'] * len(statuses))
    with mysql_conn.cursor() as cur:
        cur.execute(
            f"SELECT queue_id, asset_no, operation, payload FROM t_assets_sync_queue "
            f"WHERE status IN ({placeholders}) ORDER BY created_at ASC",
            statuses,
        )
        return cur.fetchall()


def push_one(mdb_conn, asset_no, operation, payload, dry_run):
    """payload を tbl固定資産へUPDATE/INSERTする。戻り値: (成功したか, エラーメッセージ or None)"""
    fields = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    restored = {
        FIELD_TO_ACCESS_COLUMN[name]: restore_payload_value(name, value)
        for name, value in fields.items()
        if name in FIELD_TO_ACCESS_COLUMN
    }
    if not restored and operation == 'update':
        return True, None

    cur = mdb_conn.cursor()
    try:
        if operation == 'update':
            cur.execute('SELECT COUNT(*) FROM [tbl固定資産] WHERE [資産NO] = ?', asset_no)
            if cur.fetchone()[0] == 0:
                return False, 'MDB側に資産NOが存在しません'
            set_clause = ', '.join(f'[{col}] = ?' for col in restored)
            sql = f'UPDATE [tbl固定資産] SET {set_clause} WHERE [資産NO] = ?'
            params = list(restored.values()) + [asset_no]
        else:  # insert
            cur.execute('SELECT COUNT(*) FROM [tbl固定資産] WHERE [資産NO] = ?', asset_no)
            if cur.fetchone()[0] > 0:
                return False, 'MDB側に同じ資産NOが既に存在します'
            all_fields = {'資産NO': asset_no, **restored}
            columns = ', '.join(f'[{c}]' for c in all_fields)
            placeholder_sql = ', '.join(['?'] * len(all_fields))
            sql = f'INSERT INTO [tbl固定資産] ({columns}) VALUES ({placeholder_sql})'
            params = list(all_fields.values())

        if dry_run:
            logger.info('[dry-run] asset_no=%s sql=%s params=%s', asset_no, sql, params)
        else:
            cur.execute(sql, params)
        return True, None
    except Exception as e:  # pyodbc例外・Accessロック等
        return False, str(e)[:500]
    finally:
        cur.close()


def run_push(mdb_conn, mysql_conn, retry_errors, dry_run):
    queue_rows = fetch_push_queue(mysql_conn, retry_errors)
    success = failure = 0
    for queue_id, asset_no, operation, payload in queue_rows:
        ok, err = push_one(mdb_conn, asset_no, operation, payload, dry_run)
        if ok:
            success += 1
            if not dry_run:
                with mysql_conn.cursor() as cur:
                    cur.execute(
                        "UPDATE t_assets_sync_queue SET status='done', processed_at=NOW(), error_msg='' "
                        "WHERE queue_id=%s", (queue_id,),
                    )
        else:
            failure += 1
            logger.warning('Push失敗 asset_no=%s: %s', asset_no, err)
            if not dry_run:
                with mysql_conn.cursor() as cur:
                    cur.execute(
                        "UPDATE t_assets_sync_queue SET status='error', processed_at=NOW(), error_msg=%s "
                        "WHERE queue_id=%s", (err, queue_id),
                    )
        if not dry_run:
            mysql_conn.commit()
    if not dry_run:
        mdb_conn.commit()
    logger.info('Push完了: 成功 %d件 / 失敗 %d件', success, failure)
    return success, failure


def fetch_skip_asset_nos(mysql_conn):
    """pending/error のキューが残っている資産NO（Pullでスキップ対象）を取得する。"""
    with mysql_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT asset_no FROM t_assets_sync_queue WHERE status IN ('pending', 'error')"
        )
        return {row[0] for row in cur.fetchall()}


def run_pull(mdb_conn, mysql_conn, dry_run):
    skip_asset_nos = fetch_skip_asset_nos(mysql_conn)

    cur = mdb_conn.cursor()
    cur.execute('SELECT * FROM v_assets')
    rows = cur.fetchall()
    cur.close()

    with mysql_conn.cursor() as m:
        m.execute('SELECT asset_no FROM T_ASSETS')
        existing = {row[0] for row in m.fetchall()}

    inserted = updated = skipped = 0
    for row in rows:
        values = dict(zip(PULL_COLUMNS, row))
        asset_no = values.get('asset_no')
        if not asset_no:
            continue
        if asset_no in skip_asset_nos:
            skipped += 1
            continue

        normalized = {k: pull_value_to_mysql(k, v) for k, v in values.items()}

        if dry_run:
            if asset_no in existing:
                updated += 1
            else:
                inserted += 1
            continue

        columns = list(normalized.keys())
        with mysql_conn.cursor() as m:
            if asset_no in existing:
                set_clause = ', '.join(f'{c}=%s' for c in columns if c != 'asset_no')
                params = [normalized[c] for c in columns if c != 'asset_no'] + [asset_no]
                m.execute(f'UPDATE T_ASSETS SET {set_clause} WHERE asset_no=%s', params)
                updated += 1
            else:
                col_sql = ', '.join(columns)
                ph_sql = ', '.join(['%s'] * len(columns))
                params = [normalized[c] for c in columns]
                m.execute(f'INSERT INTO T_ASSETS ({col_sql}) VALUES ({ph_sql})', params)
                inserted += 1
    if not dry_run:
        mysql_conn.commit()
    logger.info('Pull完了: 新規 %d件 / 更新 %d件 / スキップ %d件', inserted, updated, skipped)
    return inserted, updated, skipped


def main():
    parser = argparse.ArgumentParser(description='固定資産台帳 Access MDB 双方向同期')
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.ini')))
    parser.add_argument('--dry-run', action='store_true', help='MDB/MySQLへの書き込みなしで処理内容を表示')
    parser.add_argument('--retry-errors', action='store_true', help='status=error のキューも再送信対象に含める')
    args = parser.parse_args()

    cfg = load_config(args.config)

    logger.info('接続確認中...')
    mdb_conn = connect_mdb(cfg)
    mysql_conn = connect_mysql(cfg)
    logger.info('接続確認OK（MDB / MySQL）')

    try:
        queue_rows = fetch_push_queue(mysql_conn, args.retry_errors)
        if queue_rows and not args.dry_run:
            backup_mdb(cfg)

        push_success, push_failure = run_push(mdb_conn, mysql_conn, args.retry_errors, args.dry_run)
        pull_inserted, pull_updated, pull_skipped = run_pull(mdb_conn, mysql_conn, args.dry_run)

        print()
        print('==== 同期結果 ====')
        print(f'Push: 成功 {push_success} 件 / 失敗 {push_failure} 件')
        print(f'Pull: 新規 {pull_inserted} 件 / 更新 {pull_updated} 件 / スキップ {pull_skipped} 件')
    finally:
        mdb_conn.close()
        mysql_conn.close()


if __name__ == '__main__':
    main()
