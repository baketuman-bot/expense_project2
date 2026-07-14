#!/usr/bin/env python3
"""
gs2db.h2.db (旧グループウェア GSESSION) から稟議・ユーザー・組織データをCSV抽出する。

使い方:
    python3 extract_gs2db.py <gs2db.h2.dbのパス> <出力先ディレクトリ> \
        [--h2-jar PATH] [--java PATH] [--workdir PATH]

前提: Java (JRE) と H2 1.4.200 のjarファイルが必要。README.md参照。
パスワード不要（org.h2.tools.Recoverによるフォレンジック復元のため）。
"""
import argparse
import csv
import shutil
import subprocess
import sys
from pathlib import Path

from h2recover_parser import UnresolvedLob, extract_rows_for_table, parse_o0_metadata

# (CSVファイル名(拡張子なし), 実テーブル名, 出力カラム名リスト)
TARGET_TABLES = [
    ('gs_ringi', 'RNG_RNDATA', [
        'rng_sid', 'rng_title', 'rng_makedate', 'rng_applicate', 'rng_appldate',
        'rng_status', 'rng_compflg', 'rng_admcomment', 'rng_auid', 'rng_adate',
        'rng_euid', 'rng_edate', 'rng_id', 'rtp_sid', 'rtp_ver', 'rct_ver',
    ]),
    ('gs_group', 'CMN_GROUPM', [
        'grp_sid', 'grp_id', 'grp_name', 'grp_name_kn', 'grp_comment',
        'grp_auid', 'grp_adate', 'grp_euid', 'grp_edate', 'grp_sort', 'grp_jkbn',
    ]),
    ('gs_position', 'CMN_POSITION', [
        'pos_sid', 'pos_code', 'pos_name', 'pos_biko', 'pos_sort',
        'pos_auid', 'pos_adate', 'pos_euid', 'pos_edate',
    ]),
    ('gs_belong', 'CMN_BELONGM', [
        'grp_sid', 'usr_sid', 'beg_auid', 'beg_adate', 'beg_euid', 'beg_edate',
        'beg_defgrp', 'beg_grpkbn',
    ]),
]

USR_FIELDS = ['usr_sid', 'usr_lgid', 'usr_jkbn']
USR_INF_FIELDS = [
    'usi_sei', 'usi_mei', 'usi_sei_kn', 'usi_mei_kn', 'usi_syain_no',
    'usi_syozoku', 'usi_yakusyoku', 'pos_sid', 'usi_entrance_date',
]


def run_recover(h2_jar, java_bin, workdir, db_name):
    subprocess.run(
        [java_bin, '-cp', str(h2_jar), 'org.h2.tools.Recover', '-dir', str(workdir), '-db', db_name],
        check=True,
    )
    return workdir / f'{db_name}.h2.sql'


def value_to_csv(v):
    if v is None or isinstance(v, UnresolvedLob):
        return ''
    if hasattr(v, 'isoformat'):
        return v.isoformat(sep=' ')
    return str(v)


def write_csv(path, columns, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([value_to_csv(row.get(c)) for c in columns])


def merge_usr_rows(usrm_rows, inf_rows):
    """CMN_USRM(usr_sidキー) と CMN_USRM_INF(usr_sidキー) を結合する。
    usr_pswd等、USR_FIELDS/USR_INF_FIELDSに含まれない列は結果に含めない。"""
    merged = []
    for usr_sid, usrm_row in usrm_rows.items():
        inf_row = inf_rows.get(usr_sid, {})
        row = {f: usrm_row.get(f) for f in USR_FIELDS}
        row.update({f: inf_row.get(f) for f in USR_INF_FIELDS})
        merged.append(row)
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('h2_db_path', type=Path)
    parser.add_argument('out_dir', type=Path)
    parser.add_argument('--h2-jar', type=Path, default=Path(__file__).parent / 'h2-1.4.200.jar')
    parser.add_argument('--java', default='java')
    parser.add_argument('--workdir', type=Path, default=None)
    args = parser.parse_args()

    if not args.h2_db_path.exists():
        sys.exit(f'見つかりません: {args.h2_db_path}')
    if not args.h2_jar.exists():
        sys.exit(f'H2 jarが見つかりません: {args.h2_jar} (README.md参照)')

    workdir = args.workdir or (Path(__file__).parent / 'work')
    workdir.mkdir(parents=True, exist_ok=True)
    db_name = 'gs2db_src'
    shutil.copy(args.h2_db_path, workdir / f'{db_name}.h2.db')

    sql_path = run_recover(args.h2_jar, args.java, workdir, db_name)
    print(f'Recoverダンプ生成: {sql_path}')

    meta = parse_o0_metadata(sql_path)
    name_to_oid = {}
    for oid, (name, _cols) in meta.items():
        short_name = name.split('.')[-1]
        name_to_oid[short_name] = oid

    args.out_dir.mkdir(parents=True, exist_ok=True)

    for csv_name, real_name, out_columns in TARGET_TABLES:
        if real_name not in name_to_oid:
            sys.exit(f'テーブルが見つかりません: {real_name}')
        oid = name_to_oid[real_name]
        _, src_columns = meta[oid]
        skip_counter = {}
        rows = list(extract_rows_for_table(sql_path, oid, src_columns, skip_counter=skip_counter))
        write_csv(args.out_dir / f'{csv_name}.csv', out_columns, rows)
        unresolved = sum(
            1 for r in rows for v in r.values() if isinstance(v, UnresolvedLob)
        )
        skipped = skip_counter.get('skipped', 0)
        print(f'{csv_name}: {len(rows)} 件書き出し（未解決CLOB: {unresolved}、スキップ: {skipped}）')

    for required in ('CMN_USRM', 'CMN_USRM_INF'):
        if required not in name_to_oid:
            sys.exit(f'テーブルが見つかりません: {required}')

    usrm_oid = name_to_oid['CMN_USRM']
    _, usrm_cols = meta[usrm_oid]
    usrm_skip_counter = {}
    usrm_rows = {
        r['usr_sid']: r
        for r in extract_rows_for_table(sql_path, usrm_oid, usrm_cols, skip_counter=usrm_skip_counter)
    }

    inf_oid = name_to_oid['CMN_USRM_INF']
    _, inf_cols = meta[inf_oid]
    inf_skip_counter = {}
    inf_rows = {
        r['usr_sid']: r
        for r in extract_rows_for_table(sql_path, inf_oid, inf_cols, skip_counter=inf_skip_counter)
    }

    merged = merge_usr_rows(usrm_rows, inf_rows)
    write_csv(args.out_dir / 'gs_usr.csv', USR_FIELDS + USR_INF_FIELDS, merged)
    total_skipped = usrm_skip_counter.get('skipped', 0) + inf_skip_counter.get('skipped', 0)
    print(f'gs_usr: {len(merged)} 件書き出し（スキップ: {total_skipped}）')


if __name__ == '__main__':
    main()
