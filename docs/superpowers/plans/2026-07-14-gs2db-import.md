# gs2db.h2.db（GSESSION）稟議・ユーザー・組織データ取り込み Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 旧グループウェア「GSESSION」のH2データベース（`tmp/gs2db.h2.db`）から、稟議データ・ユーザー・組織情報を抽出しMySQLの新規テーブル（`GS_RINGI`/`GS_USR`/`GS_GROUP`/`GS_BELONG`/`GS_POSITION`）へ参照専用データとして取り込めるようにする。

**Architecture:** (1) Djangoに依存しない独立スクリプト（`deploy/gs2db_sync/`）が、Java + H2 1.4.200の`org.h2.tools.Recover`でパスワード不要のフォレンジック復元を行い、対象5テーブルをCSVに書き出す。(2) 新規Django管理コマンド`import_gs2db`がそのCSVを読み、`GS_*`モデルへupsertする。既存のM_User/M_Bumon等とは一切紐付けない、参照専用の独立テーブル。

**Tech Stack:** Python 3 標準ライブラリのみ（抽出スクリプト側）、Django 5.2 ORM（取り込みコマンド側）、Java + H2 1.4.200 jar（外部前提ツール、`import_assets`のAccess/ODBC同様アプリ本体の依存には含めない）。

## Global Constraints

- 本プロジェクトは本番MySQL(`expense_db`)を直接使用している。**DELETE/TRUNCATE/DROPは一切行わない。** 取り込みはすべて`update_or_create`によるupsertのみ。
- `python manage.py test` 実行時に `DJANGO_TEST_DB_NAME=expense_db` を使用しない（本番DB破壊のリスク）。既存の`expenses/test_*.py`と同様に`python manage.py test expenses.test_xxx`の形で実行する（プロジェクト側でテスト用DB権限が設定済みの前提。設定されていない場合はDjangoモデル関連タスクの自動テストは実行せず、コード自体は静的にレビューする）。
- パスワードハッシュ（`USR_PSWD`）は取り込まない（GS_USRに含めない）。
- 既存のM_User/M_Bumon/M_Post/M_BelongTo等とは紐付けない（参照専用の独立テーブル）。
- 新規db_tableは大文字指定: `GS_RINGI`, `GS_USR`, `GS_GROUP`, `GS_BELONG`, `GS_POSITION`（ユーザー指定の名称そのまま）。
- 抽出元の`tmp/gs2db.h2.db`および出力CSVには実在従業員の氏名・社員番号等の個人情報が含まれるため、gitに含めない（.gitignore対応必須）。

---

### Task 1: `.gitignore` に個人情報を含む生成物を追加

**Files:**
- Modify: `.gitignore`

**Interfaces:**
- なし（設定ファイルのみ）

- [ ] **Step 1: `.gitignore`に追記**

`.gitignore`の末尾（`deploy/windows_sync/sync_assets.log`の次の行）に以下を追加する。

```gitignore
# gs2db (旧グループウェア GSESSION) 関連 - 個人情報を含むため
tmp/*.h2.db
deploy/gs2db_sync/*.jar
deploy/gs2db_sync/csv/
deploy/gs2db_sync/work/
```

- [ ] **Step 2: 反映確認**

Run: `git status --short`
Expected: `tmp/gs2db.h2.db` が一覧に表示されなくなる（無視される）ことを確認。

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: gs2db関連の個人情報含有ファイルをgitignoreに追加"
```

---

### Task 2: Django モデル `GS_Ringi` / `GS_Usr` / `GS_Group` / `GS_Belong` / `GS_Position` を追加

**Files:**
- Modify: `expenses/models.py`（末尾に追記。現在1219行、`T_AssetsSyncQueue`クラスの後）
- Create: `expenses/migrations/0106_gs2db_legacy_tables.py`
- Test: `expenses/test_gs2db_models.py`

**Interfaces:**
- Produces: `expenses.models.GS_Ringi`（PK: `rng_sid`）, `GS_Usr`（PK: `usr_sid`）, `GS_Group`（PK: `grp_sid`）, `GS_Belong`（AutoField PK、`unique_together=[('grp_sid','usr_sid','beg_grpkbn')]`）, `GS_Position`（PK: `pos_sid`）

- [ ] **Step 1: モデル定義を`expenses/models.py`の末尾に追記**

```python


# ── GSESSION (旧グループウェア) 参照データ ─────────────────────────────
# tmp/gs2db.h2.db から deploy/gs2db_sync/extract_gs2db.py + import_gs2db
# コマンドで取り込む、参照専用の独立テーブル群。既存M_/T_系とは紐付けない。

class GS_Ringi(models.Model):
    """稟議データ本体（旧GSESSIONのRNG_RNDATAより参照専用インポート）"""

    rng_sid        = models.IntegerField("旧稟議SID", primary_key=True)
    rng_title      = models.CharField("件名", max_length=100)
    rng_makedate   = models.DateTimeField("作成日時")
    rng_applicate  = models.IntegerField("申請者旧USR_SID", null=True, blank=True)
    rng_appldate   = models.DateTimeField("申請日時", null=True, blank=True)
    rng_status     = models.IntegerField("ステータス")
    rng_compflg    = models.IntegerField("完了フラグ")
    rng_admcomment = models.CharField("管理者コメント", max_length=300, null=True, blank=True)
    rng_auid       = models.IntegerField("作成者旧USR_SID")
    rng_adate      = models.DateTimeField("作成日時(監査)")
    rng_euid       = models.IntegerField("更新者旧USR_SID")
    rng_edate      = models.DateTimeField("更新日時(監査)")
    rng_id         = models.CharField("表示用ID", max_length=120, null=True, blank=True)
    rtp_sid        = models.IntegerField("テンプレート旧SID")
    rtp_ver        = models.IntegerField("テンプレートバージョン")
    rct_ver        = models.IntegerField("カテゴリバージョン", default=0)

    def __str__(self):
        return f"{self.rng_sid} {self.rng_title}"

    class Meta:
        db_table = 'GS_RINGI'
        verbose_name = '旧稟議データ(GSESSION)'
        verbose_name_plural = '旧稟議データ(GSESSION)'
        ordering = ['-rng_sid']


class GS_Usr(models.Model):
    """ユーザー参照データ（旧GSESSIONのCMN_USRM+CMN_USRM_INFより参照専用インポート）

    パスワードハッシュ(USR_PSWD)はセキュリティ上の理由で取り込まない。
    """

    usr_sid           = models.IntegerField("旧ユーザーSID", primary_key=True)
    usr_lgid           = models.CharField("ログインID", max_length=256)
    usr_jkbn           = models.IntegerField("在籍区分")
    usi_sei            = models.CharField("姓", max_length=30, null=True, blank=True)
    usi_mei            = models.CharField("名", max_length=30, null=True, blank=True)
    usi_sei_kn         = models.CharField("姓カナ", max_length=60, null=True, blank=True)
    usi_mei_kn         = models.CharField("名カナ", max_length=60, null=True, blank=True)
    usi_syain_no       = models.CharField("社員番号", max_length=20, null=True, blank=True)
    usi_syozoku        = models.CharField("所属名", max_length=60, null=True, blank=True)
    usi_yakusyoku      = models.CharField("役職名", max_length=30, null=True, blank=True)
    pos_sid            = models.IntegerField("旧役職SID", null=True, blank=True)
    usi_entrance_date  = models.DateTimeField("入社日", null=True, blank=True)

    def __str__(self):
        return f"{self.usr_sid} {self.usi_sei}{self.usi_mei}"

    class Meta:
        db_table = 'GS_USR'
        verbose_name = '旧ユーザー(GSESSION)'
        verbose_name_plural = '旧ユーザー(GSESSION)'
        ordering = ['usr_sid']


class GS_Group(models.Model):
    """組織・グループマスタ（旧GSESSIONのCMN_GROUPMより参照専用インポート）"""

    grp_sid     = models.IntegerField("旧グループSID", primary_key=True)
    grp_id      = models.CharField("グループID", max_length=50)
    grp_name    = models.CharField("グループ名", max_length=50, null=True, blank=True)
    grp_name_kn = models.CharField("グループ名カナ", max_length=75, null=True, blank=True)
    grp_comment = models.CharField("コメント", max_length=1000, null=True, blank=True)
    grp_auid    = models.IntegerField("作成者旧USR_SID")
    grp_adate   = models.DateTimeField("作成日時")
    grp_euid    = models.IntegerField("更新者旧USR_SID")
    grp_edate   = models.DateTimeField("更新日時")
    grp_sort    = models.IntegerField("表示順")
    grp_jkbn    = models.IntegerField("状態区分")

    def __str__(self):
        return f"{self.grp_sid} {self.grp_name}"

    class Meta:
        db_table = 'GS_GROUP'
        verbose_name = '旧組織グループ(GSESSION)'
        verbose_name_plural = '旧組織グループ(GSESSION)'
        ordering = ['grp_sort', 'grp_sid']


class GS_Belong(models.Model):
    """所属（グループ-ユーザーの紐付け。旧GSESSIONのCMN_BELONGMより参照専用インポート）"""

    grp_sid    = models.IntegerField("旧グループSID")
    usr_sid    = models.IntegerField("旧ユーザーSID")
    beg_auid   = models.IntegerField("作成者旧USR_SID")
    beg_adate  = models.DateTimeField("作成日時")
    beg_euid   = models.IntegerField("更新者旧USR_SID")
    beg_edate  = models.DateTimeField("更新日時")
    beg_defgrp = models.IntegerField("デフォルトグループ区分")
    beg_grpkbn = models.IntegerField("グループ区分", null=True, blank=True)

    def __str__(self):
        return f"grp={self.grp_sid} usr={self.usr_sid}"

    class Meta:
        db_table = 'GS_BELONG'
        verbose_name = '旧所属(GSESSION)'
        verbose_name_plural = '旧所属(GSESSION)'
        unique_together = [('grp_sid', 'usr_sid', 'beg_grpkbn')]


class GS_Position(models.Model):
    """役職マスタ（旧GSESSIONのCMN_POSITIONより参照専用インポート）"""

    pos_sid   = models.IntegerField("旧役職SID", primary_key=True)
    pos_code  = models.CharField("役職コード", max_length=15)
    pos_name  = models.CharField("役職名", max_length=30)
    pos_biko  = models.CharField("備考", max_length=300, blank=True)
    pos_sort  = models.IntegerField("表示順")
    pos_auid  = models.IntegerField("作成者旧USR_SID")
    pos_adate = models.DateTimeField("作成日時")
    pos_euid  = models.IntegerField("更新者旧USR_SID")
    pos_edate = models.DateTimeField("更新日時")

    def __str__(self):
        return f"{self.pos_sid} {self.pos_name}"

    class Meta:
        db_table = 'GS_POSITION'
        verbose_name = '旧役職(GSESSION)'
        verbose_name_plural = '旧役職(GSESSION)'
        ordering = ['pos_sort', 'pos_sid']
```

- [ ] **Step 2: マイグレーションを生成**

Run: `python manage.py makemigrations expenses --name gs2db_legacy_tables`
Expected: `expenses/migrations/0106_gs2db_legacy_tables.py` が生成され、`GS_Ringi`/`GS_Usr`/`GS_Group`/`GS_Belong`/`GS_Position`の5つの`CreateModel`が含まれる。生成後、ファイルを開いて`dependencies`が`('expenses', '0105_add_supplier_item_qty_to_journal_views.py'の実際の最新ファイル名)`になっていることを確認する（自動生成されるはずだが、必ず目視確認する）。

- [ ] **Step 3: マイグレーションを適用**

Run: `python manage.py migrate expenses`
Expected: `Applying expenses.0106_gs2db_legacy_tables... OK`

- [ ] **Step 4: テストを書く（失敗させる必要はない。モデルCRUDの動作確認）**

`expenses/test_gs2db_models.py`:

```python
"""GS_* (旧GSESSION参照データ) モデルの基本CRUDテスト"""
from django.test import TestCase

from expenses.models import GS_Belong, GS_Group, GS_Position, GS_Ringi, GS_Usr


class GS2dbModelsTest(TestCase):
    def test_gs_ringi_create_and_str(self):
        obj = GS_Ringi.objects.create(
            rng_sid=1, rng_title='与信管理申請', rng_makedate='2025-06-24 16:21:28',
            rng_status=1, rng_compflg=0, rng_auid=1, rng_adate='2025-06-24 16:21:28',
            rng_euid=1, rng_edate='2025-06-24 16:21:28', rtp_sid=10, rtp_ver=1,
        )
        self.assertEqual(str(obj), '1 与信管理申請')
        self.assertEqual(GS_Ringi.objects.get(rng_sid=1).rng_title, '与信管理申請')

    def test_gs_usr_excludes_password_field(self):
        obj = GS_Usr.objects.create(
            usr_sid=100, usr_lgid='taro.yamada', usr_jkbn=1,
            usi_sei='山田', usi_mei='太郎', usi_syain_no='00123',
        )
        self.assertFalse(hasattr(obj, 'usr_pswd'))
        self.assertEqual(str(obj), '100 山田太郎')

    def test_gs_group_and_position(self):
        grp = GS_Group.objects.create(
            grp_sid=1, grp_id='G001', grp_name='経理部',
            grp_auid=1, grp_adate='2025-01-01 00:00:00',
            grp_euid=1, grp_edate='2025-01-01 00:00:00',
            grp_sort=1, grp_jkbn=1,
        )
        pos = GS_Position.objects.create(
            pos_sid=1, pos_code='P01', pos_name='課長', pos_sort=1,
            pos_auid=1, pos_adate='2025-01-01 00:00:00',
            pos_euid=1, pos_edate='2025-01-01 00:00:00',
        )
        self.assertEqual(str(grp), '1 経理部')
        self.assertEqual(str(pos), '1 課長')

    def test_gs_belong_unique_together(self):
        GS_Belong.objects.create(
            grp_sid=1, usr_sid=100, beg_auid=1, beg_adate='2025-01-01 00:00:00',
            beg_euid=1, beg_edate='2025-01-01 00:00:00', beg_defgrp=1, beg_grpkbn=1,
        )
        # 同一(grp_sid, usr_sid, beg_grpkbn)の重複はupdate_or_createで対応する想定。
        # ここでは単純作成できることのみ確認。
        self.assertEqual(GS_Belong.objects.count(), 1)
```

- [ ] **Step 5: テスト実行**

Run: `python manage.py test expenses.test_gs2db_models -v 2`
Expected: `Ran 4 tests ... OK`

（もしテスト用DB権限が未設定でエラーになる場合は、CLAUDE.mdの制約に従い`DJANGO_TEST_DB_NAME=expense_db`は絶対に使わず、DBA権限設定を待つか、コードレビューのみで代替する）

- [ ] **Step 6: Commit**

```bash
git add expenses/models.py expenses/migrations/0106_gs2db_legacy_tables.py expenses/test_gs2db_models.py
git commit -m "feat: GSESSION参照データ用のGS_*モデルを追加"
```

---

### Task 3: 管理コマンド `import_gs2db` を追加

**Files:**
- Create: `expenses/management/commands/import_gs2db.py`
- Test: `expenses/test_import_gs2db.py`

**Interfaces:**
- Consumes: `expenses.models.GS_Ringi/GS_Usr/GS_Group/GS_Belong/GS_Position`（Task 2で定義）
- Produces: `python manage.py import_gs2db <csv_dir> [--dry-run]` コマンド。`csv_dir`直下に`gs_ringi.csv`, `gs_usr.csv`, `gs_group.csv`, `gs_belong.csv`, `gs_position.csv`（すべて小文字ファイル名、UTF-8、ヘッダー行あり、ヘッダーはモデルのフィールド名と完全一致）が存在する前提。

- [ ] **Step 1: テストを書く**

`expenses/test_import_gs2db.py`:

```python
"""import_gs2db 管理コマンドのテスト"""
import csv
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from expenses.models import GS_Group, GS_Ringi


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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python manage.py test expenses.test_import_gs2db -v 2`
Expected: FAIL（`No module named 'expenses.management.commands.import_gs2db'`）

- [ ] **Step 3: コマンド実装**

`expenses/management/commands/import_gs2db.py`:

```python
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
```

- [ ] **Step 4: テスト実行して成功を確認**

Run: `python manage.py test expenses.test_import_gs2db -v 2`
Expected: `Ran 3 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add expenses/management/commands/import_gs2db.py expenses/test_import_gs2db.py
git commit -m "feat: GSESSION CSVをGS_*テーブルへupsertするimport_gs2dbコマンドを追加"
```

---

### Task 4: `h2recover_parser.py` — 値パースの基礎関数（stringdecode/split_top_level/parse_scalar）

**Files:**
- Create: `deploy/gs2db_sync/h2recover_parser.py`
- Test: `deploy/gs2db_sync/test_h2recover_parser.py`

**Interfaces:**
- Produces:
  - `stringdecode(s: str) -> str`
  - `split_top_level(s: str, sep: str = ',') -> list[str]`
  - `class UnresolvedLob: raw: str`
  - `parse_scalar(token: str)` — 戻り値は `None | int | str | datetime.datetime | UnresolvedLob`
  - `parse_values_tuple(values_str: str) -> list`

- [ ] **Step 1: ディレクトリ作成とテストファイルを書く（失敗するはず）**

`deploy/gs2db_sync/test_h2recover_parser.py`:

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd deploy/gs2db_sync && python3 -m unittest test_h2recover_parser -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'h2recover_parser'`）

- [ ] **Step 3: `h2recover_parser.py` を実装**

`deploy/gs2db_sync/h2recover_parser.py`:

```python
"""
gs2db.h2.db (旧グループウェア GSESSION) を org.h2.tools.Recover で
フォレンジック復元した際に生成されるSQLダンプ (*.h2.sql) をパースするための
純粋関数群。Java/H2への依存はなく、単体テスト可能。

用語:
- 物理テーブルは `O_<内部ID>` という無名テーブル・`C0,C1,...` という無名カラムで
  格納されている。実テーブル名・カラム名は `O_0` という内部メタテーブルに
  CREATE TABLE DDL文字列として保存されている（parse_o0_metadataで復元）。
"""
import re
from datetime import datetime


def stringdecode(s):
    """H2のSTRINGDECODE()関数と同じエスケープ規則で文字列をデコードする"""
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == '\\' and i + 1 < n:
            nc = s[i + 1]
            simple = {'n': '\n', 'r': '\r', 't': '\t', '\\': '\\', '"': '"', "'": "'"}
            if nc in simple:
                out.append(simple[nc])
                i += 2
                continue
            if nc == 'u' and i + 5 < n:
                hexs = s[i + 2:i + 6]
                try:
                    out.append(chr(int(hexs, 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def sql_unescape_quotes(s):
    """SQL文字列リテラル内の '' (エスケープされた単一引用符) を ' に戻す"""
    return s.replace("''", "'")


def split_top_level(s, sep=','):
    """括弧の深さとシングルクォート文字列を考慮して、トップレベルのsepで分割する"""
    parts = []
    depth = 0
    in_quote = False
    cur = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if in_quote:
            if ch == "'":
                if i + 1 < n and s[i + 1] == "'":
                    cur.append("''")
                    i += 2
                    continue
                in_quote = False
                cur.append(ch)
                i += 1
                continue
            cur.append(ch)
            i += 1
            continue
        if ch == "'":
            in_quote = True
            cur.append(ch)
            i += 1
            continue
        if ch == '(':
            depth += 1
            cur.append(ch)
            i += 1
            continue
        if ch == ')':
            depth -= 1
            cur.append(ch)
            i += 1
            continue
        if ch == sep and depth == 0:
            parts.append(''.join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    if cur or parts:
        parts.append(''.join(cur))
    return [p.strip() for p in parts]


class UnresolvedLob:
    """READ_CLOB_DB()/READ_BLOB_DB() など、テキスト解析だけでは値を復元できない
    ページストア内部LOB参照を表すプレースホルダ。"""

    def __init__(self, raw):
        self.raw = raw

    def __repr__(self):
        return f'UnresolvedLob({self.raw!r})'

    def __eq__(self, other):
        return isinstance(other, UnresolvedLob) and self.raw == other.raw


_STRINGDECODE_RE = re.compile(r"^STRINGDECODE\('(.*)'\)$", re.IGNORECASE | re.DOTALL)
_TIMESTAMP_RE = re.compile(r"^TIMESTAMP\s+'([^']*(?:''[^']*)*)'$", re.IGNORECASE)
_FUNC_CALL_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\(')


def parse_scalar(token):
    """INSERT ... VALUES(...) の1トークンをPython値に変換する"""
    token = token.strip()
    if token.upper() == 'NULL':
        return None

    m = _STRINGDECODE_RE.match(token)
    if m:
        return stringdecode(sql_unescape_quotes(m.group(1)))

    m = _TIMESTAMP_RE.match(token)
    if m:
        raw = sql_unescape_quotes(m.group(1))
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        raise ValueError(f'パースできないTIMESTAMPです: {raw!r}')

    if token.startswith("'") and token.endswith("'") and len(token) >= 2:
        return sql_unescape_quotes(token[1:-1])

    if _FUNC_CALL_RE.match(token):
        return UnresolvedLob(token)

    return int(token)


def parse_values_tuple(values_str):
    """`INSERT INTO ... VALUES(<values_str>)` の中身をPythonのリストに変換する"""
    return [parse_scalar(tok) for tok in split_top_level(values_str)]
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd deploy/gs2db_sync && python3 -m unittest test_h2recover_parser -v`
Expected: `OK` （全テストPASS）

- [ ] **Step 5: Commit**

```bash
git add deploy/gs2db_sync/h2recover_parser.py deploy/gs2db_sync/test_h2recover_parser.py
git commit -m "feat: H2 Recoverダンプの値パース関数(h2recover_parser)を追加"
```

---

### Task 5: `h2recover_parser.py` — テーブル名/カラム名復元と行抽出（parse_o0_metadata / extract_rows_for_table）

**Files:**
- Modify: `deploy/gs2db_sync/h2recover_parser.py`
- Modify: `deploy/gs2db_sync/test_h2recover_parser.py`
- Test fixtures: 一時ファイルはテスト内で`tempfile`を使って生成する（固定fixtureファイルは作らない）

**Interfaces:**
- Consumes: Task 4の`parse_values_tuple`, `stringdecode`, `sql_unescape_quotes`, `UnresolvedLob`
- Produces:
  - `parse_ddl_columns(ddl_text: str) -> tuple[str, list[str]] | None`
  - `parse_o0_metadata(sql_path: str | Path) -> dict[int, tuple[str, list[str]]]` — `{内部ID: (実テーブル名, [実カラム名,...])}`
  - `extract_rows_for_table(sql_path: str | Path, oid: int, columns: list[str]) -> Iterator[dict]`

- [ ] **Step 1: テストを追記（失敗するはず）**

`deploy/gs2db_sync/test_h2recover_parser.py` の末尾に追記:

```python
import tempfile
from pathlib import Path

from h2recover_parser import extract_rows_for_table, parse_ddl_columns, parse_o0_metadata


class ParseDdlColumnsTest(unittest.TestCase):
    def test_simple_table(self):
        ddl = (
            "CREATE CACHED TABLE PUBLIC.CMN_POSITION(\n"
            "    POS_SID INTEGER NOT NULL,\n"
            "    POS_CODE VARCHAR(15) NOT NULL,\n"
            "    POS_NAME VARCHAR(30) NOT NULL\n"
            ")"
        )
        name, columns = parse_ddl_columns(ddl)
        self.assertEqual(name, 'PUBLIC.CMN_POSITION')
        self.assertEqual(columns, ['POS_SID', 'POS_CODE', 'POS_NAME'])

    def test_non_create_table_returns_none(self):
        self.assertIsNone(parse_ddl_columns('CREATE SCHEMA IF NOT EXISTS FTL AUTHORIZATION GSESSION;'))


class ParseO0MetadataTest(unittest.TestCase):
    def test_resolves_table_name_and_columns(self):
        content = (
            "INSERT INTO O_0 VALUES(387, 0, 0, STRINGDECODE("
            "'CREATE CACHED TABLE PUBLIC.CMN_POSITION(\\n"
            "    POS_SID INTEGER NOT NULL,\\n"
            "    POS_CODE VARCHAR(15) NOT NULL\\n"
            ")'));\n"
            "INSERT INTO O_0 VALUES(999, 0, 0, STRINGDECODE('not a create table'));\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'dump.sql'
            path.write_text(content, encoding='utf-8')
            meta = parse_o0_metadata(path)
        self.assertEqual(meta[387], ('PUBLIC.CMN_POSITION', ['POS_SID', 'POS_CODE']))
        self.assertNotIn(999, meta)


class ExtractRowsForTableTest(unittest.TestCase):
    def test_extracts_matching_rows_only(self):
        content = (
            "INSERT INTO O_387 VALUES(1, 'P01', 'Manager');\n"
            "INSERT INTO O_3870 VALUES(1, 'X01', 'Should not match O_387');\n"
            "INSERT INTO O_387 VALUES(2, 'P02', 'Staff');\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'dump.sql'
            path.write_text(content, encoding='utf-8')
            rows = list(extract_rows_for_table(path, 387, ['POS_SID', 'POS_CODE', 'POS_NAME']))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {'pos_sid': 1, 'pos_code': 'P01', 'pos_name': 'Manager'})
        self.assertEqual(rows[1], {'pos_sid': 2, 'pos_code': 'P02', 'pos_name': 'Staff'})
```

- [ ] **Step 2: テスト実行して失敗を確認**

Run: `cd deploy/gs2db_sync && python3 -m unittest test_h2recover_parser -v`
Expected: FAIL（`ImportError: cannot import name 'parse_ddl_columns'`）

- [ ] **Step 3: `h2recover_parser.py` に関数を追記**

`deploy/gs2db_sync/h2recover_parser.py` の末尾に追記:

```python


_CREATE_TABLE_RE = re.compile(
    r'CREATE\s+(?:CACHED\s+|MEMORY\s+)?TABLE\s+(?:IF NOT EXISTS\s+)?([A-Za-z0-9_."]+)\s*\((.*)\)\s*$',
    re.IGNORECASE | re.DOTALL,
)


def parse_ddl_columns(ddl_text):
    """CREATE TABLE DDL文字列からテーブル名とカラム名リストを取り出す。
    CREATE TABLE文でなければNoneを返す。"""
    m = _CREATE_TABLE_RE.search(ddl_text)
    if not m:
        return None
    table_name = m.group(1)
    body = m.group(2)
    columns = []
    for col_def in split_top_level(body):
        col_def = col_def.strip()
        if not col_def:
            continue
        if col_def.upper().startswith(('PRIMARY', 'CONSTRAINT', 'FOREIGN', 'UNIQUE')):
            continue
        columns.append(col_def.split()[0])
    return table_name, columns


_O0_ROW_RE = re.compile(r"^INSERT INTO O_0 VALUES\((\d+), (-?\d+), (-?\d+), STRINGDECODE\('(.*)'\)\);\s*$")


def parse_o0_metadata(sql_path):
    """O_0メタテーブルのINSERT行から {内部ID: (実テーブル名, [実カラム名,...])} を復元する"""
    result = {}
    with open(sql_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = _O0_ROW_RE.match(line)
            if not m:
                continue
            oid, _c1, _c2, raw = m.groups()
            ddl = stringdecode(sql_unescape_quotes(raw))
            parsed = parse_ddl_columns(ddl)
            if parsed:
                result[int(oid)] = parsed
    return result


def extract_rows_for_table(sql_path, oid, columns):
    """物理テーブル O_<oid> のINSERT行をスキャンし、実カラム名(小文字)をキーとする
    dictを1行ずつyieldする。"""
    marker = f'INSERT INTO O_{oid} VALUES('
    pattern = re.compile(rf'^INSERT INTO O_{oid} VALUES\((.*)\);\s*$')
    lower_columns = [c.lower() for c in columns]
    with open(sql_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if marker not in line:
                continue
            m = pattern.match(line)
            if not m:
                continue
            values = parse_values_tuple(m.group(1))
            if len(values) != len(lower_columns):
                continue
            yield dict(zip(lower_columns, values))
```

- [ ] **Step 4: テスト実行して成功を確認**

Run: `cd deploy/gs2db_sync && python3 -m unittest test_h2recover_parser -v`
Expected: `OK` （全テストPASS）

- [ ] **Step 5: Commit**

```bash
git add deploy/gs2db_sync/h2recover_parser.py deploy/gs2db_sync/test_h2recover_parser.py
git commit -m "feat: O_0メタデータからのテーブル名/カラム名復元と行抽出を追加"
```

---

### Task 6: `extract_gs2db.py` — 抽出オーケストレーションスクリプト

**Files:**
- Create: `deploy/gs2db_sync/extract_gs2db.py`
- Test: `deploy/gs2db_sync/test_extract_gs2db.py`

**Interfaces:**
- Consumes: `deploy/gs2db_sync/h2recover_parser.py` の `UnresolvedLob`, `extract_rows_for_table`, `parse_o0_metadata`
- Produces:
  - `value_to_csv(v) -> str`
  - `write_csv(path, columns: list[str], rows: list[dict]) -> None`
  - `merge_usr_rows(usrm_rows: dict[int, dict], inf_rows: dict[int, dict]) -> list[dict]`
  - CLI: `python3 extract_gs2db.py <gs2db.h2.dbのパス> <出力先ディレクトリ> [--h2-jar PATH] [--java PATH] [--workdir PATH]`

- [ ] **Step 1: テストを書く（失敗するはず）**

`deploy/gs2db_sync/test_extract_gs2db.py`:

```python
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
```

- [ ] **Step 2: テスト実行して失敗を確認**

Run: `cd deploy/gs2db_sync && python3 -m unittest test_extract_gs2db -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'extract_gs2db'`）

- [ ] **Step 3: `extract_gs2db.py` を実装**

`deploy/gs2db_sync/extract_gs2db.py`:

```python
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
        rows = list(extract_rows_for_table(sql_path, oid, src_columns))
        write_csv(args.out_dir / f'{csv_name}.csv', out_columns, rows)
        unresolved = sum(
            1 for r in rows for v in r.values() if isinstance(v, UnresolvedLob)
        )
        print(f'{csv_name}: {len(rows)} 件書き出し（未解決CLOB: {unresolved}）')

    for required in ('CMN_USRM', 'CMN_USRM_INF'):
        if required not in name_to_oid:
            sys.exit(f'テーブルが見つかりません: {required}')

    usrm_oid = name_to_oid['CMN_USRM']
    _, usrm_cols = meta[usrm_oid]
    usrm_rows = {r['usr_sid']: r for r in extract_rows_for_table(sql_path, usrm_oid, usrm_cols)}

    inf_oid = name_to_oid['CMN_USRM_INF']
    _, inf_cols = meta[inf_oid]
    inf_rows = {r['usr_sid']: r for r in extract_rows_for_table(sql_path, inf_oid, inf_cols)}

    merged = merge_usr_rows(usrm_rows, inf_rows)
    write_csv(args.out_dir / 'gs_usr.csv', USR_FIELDS + USR_INF_FIELDS, merged)
    print(f'gs_usr: {len(merged)} 件書き出し')


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: テスト実行して成功を確認**

Run: `cd deploy/gs2db_sync && python3 -m unittest test_extract_gs2db -v`
Expected: `OK` （全テストPASS）

- [ ] **Step 5: Commit**

```bash
git add deploy/gs2db_sync/extract_gs2db.py deploy/gs2db_sync/test_extract_gs2db.py
git commit -m "feat: gs2db.h2.dbからCSV抽出するextract_gs2db.pyスクリプトを追加"
```

---

### Task 7: セットアップ手順README追加

**Files:**
- Create: `deploy/gs2db_sync/README.md`

**Interfaces:**
- なし（ドキュメントのみ）

- [ ] **Step 1: README作成**

`deploy/gs2db_sync/README.md`:

```markdown
# gs2db.h2.db (旧グループウェア GSESSION) 稟議・ユーザー・組織データ同期

旧グループウェア「GSESSION」のH2データベースファイル（`*.h2.db`、レガシー
PageStore形式）から、稟議データ・ユーザー・組織情報を抽出しMySQLの
`GS_RINGI`/`GS_USR`/`GS_GROUP`/`GS_BELONG`/`GS_POSITION`テーブルへ
参照専用データとして取り込むためのツール一式。

パスワード不明でも読める「フォレンジック復元」方式（`org.h2.tools.Recover`）
を使うため、GSESSION側のDB認証情報は不要。

## セットアップ（初回のみ）

1. Java (JRE 17以上) をインストール
   ```bash
   sudo apt-get update
   sudo apt-get install -y default-jre-headless
   java -version   # 確認
   ```
2. H2 1.4.200 のjarを取得（レガシーPageStore形式を読める最後のバージョン）
   ```bash
   curl -sL -o deploy/gs2db_sync/h2-1.4.200.jar \
     https://repo1.maven.org/maven2/com/h2database/h2/1.4.200/h2-1.4.200.jar
   ```
   （このjarは個人情報を含まないが、リポジトリ容量の都合上gitignore対象。
   セットアップの都度ダウンロードすること）

## 使い方

```bash
# 1. gs2db.h2.db の最新コピーを用意する（例: tmp/gs2db.h2.db）

# 2. CSV抽出
cd deploy/gs2db_sync
python3 extract_gs2db.py ../../tmp/gs2db.h2.db csv/

# 3. 抽出結果を確認（--dry-run で件数・先頭数件を確認してから本実行）
cd ../..
python manage.py import_gs2db deploy/gs2db_sync/csv/ --dry-run
python manage.py import_gs2db deploy/gs2db_sync/csv/
```

`gs2db.h2.db`の新しいコピーが提供されるたびに、上記2〜3を再実行すれば
`GS_*`テーブルが最新化される（`update_or_create`によるupsertのみ。
DELETE/TRUNCATEは一切行わない）。

## 制約・既知の制限

- パスワードハッシュ（`USR_PSWD`）は取り込まない。
- `RNG_TEMPLATE.RTP_FORM`など、H2ページストア内部にLOBとして保存されている
  大きなテキスト値は、テキスト解析だけでは復元できない（該当行はログに
  「未解決CLOB」件数として表示され、該当カラムはNULLになる）。今回の
  取り込み対象5テーブルにはCLOB列を含まないため実害はない。
- 抽出元ファイル・CSV出力には実在従業員の氏名・社員番号等が含まれるため
  `.gitignore`で除外している。取り扱いに注意すること。
```

- [ ] **Step 2: Commit**

```bash
git add deploy/gs2db_sync/README.md
git commit -m "docs: gs2db_syncのセットアップ・使い方READMEを追加"
```

---

### Task 8: 実データでの手動統合検証

**Files:**
- なし（コード変更なし、動作確認のみ）

**Interfaces:**
- Consumes: Task 1〜7ですべての実装物

- [ ] **Step 1: Java/H2 jarのセットアップ確認**

Run: `java -version && ls deploy/gs2db_sync/h2-1.4.200.jar`
Expected: Javaのバージョン表示、jarファイルが存在する。なければTask 7のREADME手順でセットアップする。

- [ ] **Step 2: 実ファイルでCSV抽出を実行**

Run:
```bash
cd deploy/gs2db_sync
python3 extract_gs2db.py ../../tmp/gs2db.h2.db csv/
```
Expected: 標準出力に以下のような件数が表示される（今回のスナップショットの参考値。厳密な一致は不要、数百〜数万件のオーダーで出力されていることを確認する）
```
gs_ringi: 828 件書き出し（未解決CLOB: 0）
gs_group: 63 件書き出し（未解決CLOB: 0）
gs_position: 26 件書き出し（未解決CLOB: 0）
gs_belong: 675 件書き出し（未解決CLOB: 0）
gs_usr: 595 件書き出し
```
`deploy/gs2db_sync/csv/`配下に5つのCSVファイルが生成されていることを確認する。

- [ ] **Step 3: CSVの中身を目視確認**

Run: `head -3 deploy/gs2db_sync/csv/gs_ringi.csv deploy/gs2db_sync/csv/gs_usr.csv`
Expected: ヘッダー行と、日本語の件名・氏名等が文字化けせずに表示される。

- [ ] **Step 4: dry-runでインポート内容を確認**

Run: `python manage.py import_gs2db deploy/gs2db_sync/csv/ --dry-run`
Expected: 各テーブルについて読み込み件数と先頭3件のプレビューが表示され、末尾に「--dry-run モード: DBへの書き込みはスキップしました」と表示される。

- [ ] **Step 5: 本インポートを実行**

Run: `python manage.py import_gs2db deploy/gs2db_sync/csv/`
Expected: 各テーブルについて「新規 N 件 / 更新 0 件」（初回実行のため更新は0件）と表示される。

- [ ] **Step 6: MySQL側で件数を確認**

Django shellから確認する:

Run: `python manage.py shell -c "from expenses.models import GS_Ringi, GS_Usr, GS_Group, GS_Belong, GS_Position; print(GS_Ringi.objects.count(), GS_Usr.objects.count(), GS_Group.objects.count(), GS_Belong.objects.count(), GS_Position.objects.count())"`
Expected: Step 2で表示された件数と一致する5つの数値が表示される。

- [ ] **Step 7: 再実行してupsertが冪等であることを確認**

Run: `python manage.py import_gs2db deploy/gs2db_sync/csv/`
Expected: 全テーブルで「新規 0 件 / 更新 N 件」と表示される（Step 5と同じ件数のNが「更新」に回っている）。Step 6の件数が変化していないことを確認する。

---

## 完了条件

- [ ] Task 1〜7の自動テストがすべてPASSしている
- [ ] Task 8の手動検証で実データの取り込みが確認できている
- [ ] `tmp/gs2db.h2.db` および `deploy/gs2db_sync/csv/` がgitに含まれていない（`git status`で確認）
