# 仕訳明細の分割機能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 仕訳入力画面で1つの申請明細を複数の勘定科目・税区分に分割できるようにする（仕様書: `docs/superpowers/specs/2026-07-06-journal-split-design.md`）。

**Architecture:** `T_DocumentContent` に自己参照FK `split_from` を追加し、分割行を明細行の複製として作る。デフォルトマネージャで分割行を除外することで申請側は無改修。仕訳系ビュー（journal_detail_api / journal_save / journal_csv 等）だけが分割行を扱う。

**Tech Stack:** Django 5.2.6 / Python 3.12 / MySQL 8.0 / openpyxl（既存構成のまま。新規依存なし）

## Global Constraints

- **本番DB (`expense_db`) 直結。** `DELETE` / `TRUNCATE` / `DROP` / `manage.py flush` 禁止。マイグレーションは `AddField` とビュー再作成（`CREATE OR REPLACE VIEW`）のみ。
- **`DJANGO_TEST_DB_NAME=expense_db` を絶対に使わない。** テストは自動で `test_expense_db` を使う。各テスト実行前に環境変数が未設定であることを確認する。
- テスト実行コマンド（Windows側から実行。プロジェクトはWSL内、venvは `.venv`）:
  ```
  wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split -v 2 --keepdb
  ```
- manage.py 系コマンドはすべて同じ形式（`wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py <cmd>`）で実行する。
- コミットは `master` ブランチに直接行う。ブランチ・PR不要。
- コード内コメント・ラベルは日本語。既存コードのスタイル（インデント・整列）に合わせる。
- 仕様書は migration 番号を 0088 と書いているが、**実際の最新は 0096 のため 0097 / 0098 を使う**（Task 10 で仕様書も修正）。

## 重要な Django 上の注意（全タスク共通）

- カスタムデフォルトマネージャ導入後、**逆参照マネージャ（`doc.contents` と `parent.splits`）はどちらも分割行除外フィルタを継承する**。`doc.contents` の除外は狙い通りだが、**`parent.splits.all()` は常に空になる**ので絶対に使わない。分割行の取得は必ず `T_DocumentContent.all_objects.filter(split_from=parent)` を使う。
- `get_object_or_404(T_DocumentContent, pk)` はデフォルトマネージャを使うため分割行が404になる。仕訳系ビューでは `get_object_or_404(T_DocumentContent.all_objects, pk=pk)` を使う。
- `obj.refresh_from_db()` と CASCADE 削除は `_base_manager`（無フィルタ）を使うため分割行でも正常に動く。

---

### Task 1: `split_from` フィールドとマネージャ（migration 0097）

**Files:**
- Modify: `expenses/models.py`（`T_DocumentContent`、644行目付近）
- Create: `expenses/migrations/0097_add_split_from.py`（makemigrations で生成）
- Create: `expenses/test_journal_split.py`

**Interfaces:**
- Produces: `T_DocumentContent.split_from`（FK, null可, `db_column='split_from_id'`, `related_name='splits'`）、`T_DocumentContent.objects`（分割行除外）、`T_DocumentContent.all_objects`（全件）。後続タスクはすべてこれに依存。
- Produces: テスト用 `JournalSplitFixtureMixin`（後続タスクのテストが継承）。

- [ ] **Step 1: 環境変数の安全確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- bash -c 'echo ${DJANGO_TEST_DB_NAME:-unset}'`
Expected: `unset`（`expense_db` が表示された場合は作業を中断してユーザーに報告する）

- [ ] **Step 2: 失敗するテストを書く**

`expenses/test_journal_split.py` を新規作成:

```python
"""仕訳明細の分割機能（split_from）のテスト"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class JournalSplitFixtureMixin:
    """FNS済み申請 + 仕訳対象の元明細1件を作る共通フィクスチャ"""

    @classmethod
    def setUpTestData(cls):
        cls.status_fns, _ = M_Status.objects.get_or_create(
            status_cd='FNS', defaults={'status_name': '最終承認'}
        )
        grp, _ = M_DocumentGroup.objects.get_or_create(
            menu_group='PAY',
            defaults={'menu_group_name': '支出伺い', 'category': 'expense', 'menu_order': 1},
        )
        cls.doc_type, _ = M_DocumentType.objects.get_or_create(
            document_type_id=1,
            defaults={'document_type_name': 'テスト種別', 'menu_group': grp},
        )
        cls.account, _ = M_Account.objects.get_or_create(
            account_cd='670', defaults={'account_name': '旅費交通費'}
        )
        cls.account2, _ = M_Account.objects.get_or_create(
            account_cd='671', defaults={'account_name': '交際費'}
        )
        cls.user, _ = User.objects.get_or_create(
            man_number='JSP001',
            defaults={'username': 'journal_split_user', 'user_name': '仕訳太郎'},
        )
        cls.doc = T_Document.objects.create(
            document_type=cls.doc_type,
            title='仕訳分割テスト申請',
            man_number=cls.user,
            status_cd=cls.status_fns,
        )
        # 内税・税込11,000円（消費税1,000円）の元明細
        cls.parent = T_DocumentContent.objects.create(
            document=cls.doc,
            date='2026-07-01',
            account=cls.account,
            amount=Decimal('11000'),
            consumption_tax=Decimal('1000'),
            consumption_kbn=0,
            settle_kbn='CAS_INPRO',
            purpose='会議費用',
            shiharaisaki='テスト商店',
        )

    def _create_split(self, **extra):
        """元明細から分割行を直接作る（APIを介さないテスト用ヘルパ）"""
        defaults = dict(
            document=self.doc, date='2026-07-01', account=self.account,
            settle_kbn='CAS_INPRO', purpose='会議費用', shiharaisaki='テスト商店',
            consumption_kbn=0, split_from=self.parent,
        )
        defaults.update(extra)
        return T_DocumentContent.all_objects.create(**defaults)


class SplitFromModelTest(JournalSplitFixtureMixin, TestCase):
    """split_from フィールドとマネージャのテスト"""

    def test_split_from_field_exists(self):
        field = T_DocumentContent._meta.get_field('split_from')
        self.assertTrue(field.null)
        self.assertEqual(field.remote_field.model, T_DocumentContent)
        self.assertEqual(field.db_column, 'split_from_id')

    def test_default_manager_excludes_split_rows(self):
        split = self._create_split()
        pks = set(T_DocumentContent.objects.values_list('document_detail_id', flat=True))
        self.assertIn(self.parent.pk, pks)
        self.assertNotIn(split.pk, pks)

    def test_all_objects_includes_split_rows(self):
        split = self._create_split()
        pks = set(T_DocumentContent.all_objects.values_list('document_detail_id', flat=True))
        self.assertIn(split.pk, pks)

    def test_related_manager_excludes_split_rows(self):
        """申請詳細・合計計算が使う doc.contents に分割行が現れないこと"""
        split = self._create_split()
        pks = [c.pk for c in self.doc.contents.all()]
        self.assertIn(self.parent.pk, pks)
        self.assertNotIn(split.pk, pks)

    def test_split_rows_fetchable_via_all_objects_filter(self):
        """parent.splits はデフォルトマネージャの影響で常に空になるため使わない。
        分割行の取得は all_objects.filter(split_from=...) を使う"""
        split = self._create_split()
        got = list(T_DocumentContent.all_objects.filter(split_from=self.parent))
        self.assertEqual([split.pk], [s.pk for s in got])
```

- [ ] **Step 3: テストが失敗することを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split -v 2 --keepdb`
Expected: FAIL / ERROR（`split_from` フィールドが存在しない、`all_objects` が存在しない）

- [ ] **Step 4: モデルを実装**

`expenses/models.py` — `class T_DocumentContent(models.Model):`（644行目）の**直前**にマネージャを追加:

```python
class DocumentContentManager(models.Manager):
    """仕訳分割行（split_from が設定された行）を除外するデフォルトマネージャ。

    逆参照（doc.contents）にもこのフィルタが継承されるため、
    申請詳細・合計計算・CSV出力等の申請側コードには分割行が現れない。
    分割行を含めて扱う仕訳系ビューは all_objects を使うこと。
    """
    def get_queryset(self):
        return super().get_queryset().filter(split_from__isnull=True)
```

`T_DocumentContent` の `journal_discription_cre` フィールド定義（692行目付近）の直後に追加:

```python
    # 仕訳分割: 元明細への自己参照（NULL=通常明細、非NULL=仕訳入力で作られた分割行）
    split_from = models.ForeignKey(
        'self',
        verbose_name="分割元明細",
        null=True, blank=True,
        on_delete=models.CASCADE,
        db_column='split_from_id',
        related_name='splits',
        db_comment='仕訳分割の元明細ID（NULL=通常明細）',
    )

    objects     = DocumentContentManager()  # 分割行を除外（申請側の既定）
    all_objects = models.Manager()          # 全件（仕訳系ビュー専用）
```

※ `objects` を先に定義することでデフォルトマネージャになる。マネージャは migration に影響しない（`use_in_migrations=False` が既定）。

- [ ] **Step 5: マイグレーション生成**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py makemigrations expenses -n add_split_from`
Expected: `expenses/migrations/0097_add_split_from.py` が生成され、操作が `AddField` 1件のみであることを目視確認（それ以外の操作が混ざっていたら異常 — 中断して調査）。

- [ ] **Step 6: テストが通ることを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split -v 2 --keepdb`
Expected: PASS（5件）

- [ ] **Step 7: 既存テストのリグレッション確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.tests -v 1 --keepdb`
Expected: PASS（既存テストが分割行除外マネージャで壊れていないこと）

- [ ] **Step 8: 本番DBへマイグレーション適用（AddFieldのみ・非破壊）**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py migrate expenses`
Expected: `Applying expenses.0097_add_split_from... OK`

- [ ] **Step 9: コミット**

```bash
git add expenses/models.py expenses/migrations/0097_add_split_from.py expenses/test_journal_split.py
git commit -m "feat: T_DocumentContentに仕訳分割用split_fromフィールドとマネージャを追加"
```

---

### Task 2: DBビューに split_from_id を追加（migration 0098）

**Files:**
- Modify: `expenses/view_sqls.py`（`_V_DOCUMENTCONTENTS` 149行目付近 / `_V_JOURNALDOCUMENTS` 222行目付近）
- Create: `expenses/migrations/0098_add_split_from_to_views.py`
- Test: `expenses/test_journal_split.py`

**Interfaces:**
- Produces: `v_documentcontents.split_from_id` / `v_journaldocuments.split_from_id` 列（Task 8 の ORDER BY が使用）。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_journal_split.py` に追加:

```python
class ViewSqlSplitFromTest(TestCase):
    """DBビュー定義に split_from_id が含まれること"""

    def test_v_documentcontents_has_split_from(self):
        from expenses.view_sqls import _V_DOCUMENTCONTENTS
        self.assertIn('dc.split_from_id', _V_DOCUMENTCONTENTS)

    def test_v_journaldocuments_has_split_from(self):
        from expenses.view_sqls import _V_JOURNALDOCUMENTS
        self.assertIn('vdc.split_from_id', _V_JOURNALDOCUMENTS)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split.ViewSqlSplitFromTest -v 2 --keepdb`
Expected: FAIL（2件とも）

- [ ] **Step 3: view_sqls.py を修正**

`_V_DOCUMENTCONTENTS`（151行目 `dc.document_detail_id,` の直後）に追加:

```sql
  dc.split_from_id,
```

`_V_JOURNALDOCUMENTS`（226行目 `vdc.document_detail_id,` の直後）に追加:

```sql
  vdc.split_from_id,
```

- [ ] **Step 4: マイグレーション作成**

`expenses/migrations/0098_add_split_from_to_views.py` を新規作成（0096 のパターンを踏襲）:

```python
import warnings
from django.db import migrations
from expenses.view_sqls import ALL_VIEWS


def recreate_views(apps, schema_editor):
    # v_journaldocuments は v_documentcontents を参照するため、この順で再作成する
    with schema_editor.connection.cursor() as cur:
        for name in ('v_documentcontents', 'v_journaldocuments'):
            try:
                cur.execute(ALL_VIEWS[name])
            except Exception as e:
                warnings.warn(f"[0098] {name} VIEW の再作成をスキップ ({e})")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('expenses', '0097_add_split_from')]

    operations = [
        migrations.RunPython(recreate_views, reverse_code=noop),
    ]
```

- [ ] **Step 5: テストが通ることを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split -v 2 --keepdb`
Expected: PASS

- [ ] **Step 6: 本番DBへ適用（CREATE OR REPLACE VIEW のみ・非破壊）**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py migrate expenses`
Expected: `Applying expenses.0098_add_split_from_to_views... OK`（warning が出た場合は内容を確認して報告）

- [ ] **Step 7: コミット**

```bash
git add expenses/view_sqls.py expenses/migrations/0098_add_split_from_to_views.py expenses/test_journal_split.py
git commit -m "feat: v_documentcontents/v_journaldocumentsにsplit_from_id列を追加"
```

---

### Task 3: 分割作成・削除API（journal_split / journal_split_delete）

**Files:**
- Modify: `expenses/views.py`（`journal_save` の直後、5660行目付近に追加）
- Modify: `expenses/urls.py`（79行目 `journal_save` の path の直後）
- Test: `expenses/test_journal_split.py`

**Interfaces:**
- Consumes: Task 1 の `split_from` / `all_objects`。
- Produces: `POST /settings/settlement/journal/<pk>/split/` → `{'ok': True, 'row': {...}}`、`POST /settings/settlement/journal/<pk>/delete/` → `{'ok': True}`。row のキー: `pk, parent_pk, document_id, account_name, date, applicant, purpose, settle_kbn, settle_label`（Task 7 のJSが使用）。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_journal_split.py` に追加:

```python
class JournalSplitApiTest(JournalSplitFixtureMixin, TestCase):
    """分割作成・削除APIのテスト"""

    def setUp(self):
        self.client.force_login(self.user)

    def test_split_creates_row(self):
        res = self.client.post(f'/settings/settlement/journal/{self.parent.pk}/split/')
        self.assertEqual(res.status_code, 200)
        d = res.json()
        self.assertTrue(d['ok'])
        split = T_DocumentContent.all_objects.get(pk=d['row']['pk'])
        self.assertEqual(split.split_from_id, self.parent.pk)
        self.assertEqual(split.settle_kbn, 'CAS_INPRO')
        self.assertEqual(split.account_id, '670')
        self.assertIsNone(split.amount)            # 申請金額はコピーしない
        self.assertIsNone(split.consumption_tax)   # 消費税もコピーしない
        self.assertFalse(split.journal_done)
        self.assertEqual(d['row']['parent_pk'], self.parent.pk)

    def test_split_of_split_returns_400(self):
        split = self._create_split()
        res = self.client.post(f'/settings/settlement/journal/{split.pk}/split/')
        self.assertEqual(res.status_code, 400)

    def test_split_requires_post(self):
        res = self.client.get(f'/settings/settlement/journal/{self.parent.pk}/split/')
        self.assertEqual(res.status_code, 405)

    def test_delete_split_row(self):
        split = self._create_split()
        res = self.client.post(f'/settings/settlement/journal/{split.pk}/delete/')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(T_DocumentContent.all_objects.filter(pk=split.pk).exists())

    def test_delete_parent_returns_400_and_keeps_row(self):
        res = self.client.post(f'/settings/settlement/journal/{self.parent.pk}/delete/')
        self.assertEqual(res.status_code, 400)
        self.assertTrue(T_DocumentContent.all_objects.filter(pk=self.parent.pk).exists())
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split.JournalSplitApiTest -v 2 --keepdb`
Expected: FAIL（404: URLが存在しない）

- [ ] **Step 3: ビューを実装**

`expenses/views.py` — `journal_save` 関数の直後（5660行目付近、`_JNL_IDX_DENPYO` 定義の前）に追加:

```python
# 分割行にコピーするフィールド（amount / consumption_tax は申請データのため元行にのみ残す）
_SPLIT_COPY_FIELDS = [
    'document', 'date', 'account', 'tekikaku_cd', 'shiharaisaki', 'purpose',
    'corpo_card', 'corpo_card_no', 'settle_kbn', 'consumption_kbn',
]


@login_required
def journal_split(request, pk):
    """AJAX POST: 明細1件から仕訳分割行を作成する（元行のみ指定可）"""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)

    parent = get_object_or_404(T_DocumentContent.all_objects, pk=pk)
    if parent.split_from_id is not None:
        return JsonResponse(
            {'ok': False, 'error': '分割行をさらに分割することはできません'}, status=400)

    split = T_DocumentContent(split_from=parent)
    for f in _SPLIT_COPY_FIELDS:
        setattr(split, f, getattr(parent, f))
    split.save()

    return JsonResponse({
        'ok': True,
        'row': {
            'pk':           split.document_detail_id,
            'parent_pk':    parent.document_detail_id,
            'document_id':  parent.document_id,
            'account_name': split.account.account_name if split.account else '',
            'date':         split.date.strftime('%Y-%m-%d') if split.date else '',
            'applicant':    str(parent.document.man_number) if parent.document.man_number else '',
            'purpose':      split.purpose or '',
            'settle_kbn':   split.settle_kbn or '',
            'settle_label': _JOURNAL_KBN_LABEL.get(split.settle_kbn, split.settle_kbn or ''),
        },
    })


@login_required
def journal_split_delete(request, pk):
    """AJAX POST: 仕訳分割行を削除する。

    split_from が NULL の行（=申請明細そのもの）は絶対に削除しない。
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)

    content = get_object_or_404(T_DocumentContent.all_objects, pk=pk)
    if content.split_from_id is None:
        return JsonResponse(
            {'ok': False, 'error': '申請明細は削除できません（分割行のみ削除可）'}, status=400)

    content.delete()
    return JsonResponse({'ok': True})
```

- [ ] **Step 4: URLを追加**

`expenses/urls.py` の `journal_save` の行（79行目）の直後に追加:

```python
    path("settings/settlement/journal/<int:pk>/split/",  views.journal_split,        name="journal_split"),
    path("settings/settlement/journal/<int:pk>/delete/", views.journal_split_delete, name="journal_split_delete"),
```

- [ ] **Step 5: テストが通ることを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split -v 2 --keepdb`
Expected: PASS

- [ ] **Step 6: コミット**

```bash
git add expenses/views.py expenses/urls.py expenses/test_journal_split.py
git commit -m "feat: 仕訳分割行の作成・削除APIを追加"
```

---

### Task 4: journal_save の分割対応とグループ合計チェック

**Files:**
- Modify: `expenses/views.py`（`journal_save`: 5590-5659行 / 直前にヘルパ追加）
- Test: `expenses/test_journal_split.py`

**Interfaces:**
- Consumes: Task 1 の `all_objects` / `split_from`。
- Produces: `_journal_group_totals(parent)` → `{'has_split': bool, 'group_total': str, 'expected': str, 'mismatch': bool}`（Task 5 も使用）。`journal_save` レスポンスに `'group'` キー追加。分割行は POST `account_cd` で借方科目変更可。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_journal_split.py` に追加:

```python
class JournalSaveSplitTest(JournalSplitFixtureMixin, TestCase):
    """journal_save の分割行対応テスト"""

    def setUp(self):
        self.client.force_login(self.user)
        self.split = self._create_split()

    def _post(self, pk, **extra):
        data = {
            'journal_amont':           '3000',
            'consumption_tax':         '300',
            'journal_tax_kbn':         '312',
            'journal_tax_rate':        '10%',
            'journal_discription_deb': 'テスト適用',
        }
        data.update(extra)
        return self.client.post(f'/settings/settlement/journal/{pk}/save/', data)

    def test_split_row_done_without_credit(self):
        """分割行は貸方なしで journal_done=True になる"""
        res = self._post(self.split.pk)
        self.assertTrue(res.json()['journal_done'])

    def test_parent_still_requires_credit(self):
        """元行は従来どおり貸方必須"""
        res = self._post(self.parent.pk)
        self.assertFalse(res.json()['journal_done'])
        fields = {m['field'] for m in res.json()['missing']}
        self.assertIn('account_cd_cre', fields)

    def test_split_account_cd_updated(self):
        """分割行のみ借方科目を変更できる"""
        self._post(self.split.pk, account_cd='671')
        s = T_DocumentContent.all_objects.get(pk=self.split.pk)
        self.assertEqual(s.account_id, '671')

    def test_parent_account_cd_ignored(self):
        """元行への account_cd POST は無視される"""
        self._post(self.parent.pk, account_cd='671')
        p = T_DocumentContent.all_objects.get(pk=self.parent.pk)
        self.assertEqual(p.account_id, '670')

    def test_credit_posted_to_split_is_ignored(self):
        """分割行に貸方値をPOSTしても保存されない"""
        self._post(self.split.pk, account_cd_cre='41400', journal_amount_cre='999',
                   journal_discription_cre='貸方摘要')
        s = T_DocumentContent.all_objects.get(pk=self.split.pk)
        self.assertIsNone(s.account_cd_cre)
        self.assertIsNone(s.journal_amount_cre)
        self.assertIsNone(s.journal_discription_cre)

    def test_group_mismatch_flag(self):
        """元行+分割行の借方合計 ≠ 税込金額のとき mismatch=True。
        フィクスチャは内税・税込11,000円なので期待値は11,000"""
        # 元行 7,000+700 / 分割 3,000+300 → 合計 11,000 → 一致
        self._post(self.parent.pk, journal_amont='7000', consumption_tax='700',
                   account_cd_cre='41400', journal_amount_cre='7700',
                   journal_discription_cre='摘要')
        res = self._post(self.split.pk)
        self.assertFalse(res.json()['group']['mismatch'])
        # 分割を 4,000+400 に変更 → 合計 12,100 → 不一致
        res = self._post(self.split.pk, journal_amont='4000', consumption_tax='400')
        self.assertTrue(res.json()['group']['mismatch'])
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split.JournalSaveSplitTest -v 2 --keepdb`
Expected: FAIL（分割行の save が404、または journal_done=False）

- [ ] **Step 3: ヘルパと journal_save を実装**

`expenses/views.py` — `journal_save`（5589行目）の**直前**にヘルパを追加:

```python
def _journal_group_totals(parent):
    """元行＋分割行の借方(税抜+税)合計と、元行の税込金額(円換算)を比較する。

    parent.splits は分割行除外マネージャの影響で使えないため all_objects で取得する。
    """
    splits = list(
        T_DocumentContent.all_objects
        .filter(split_from=parent)
        .order_by('document_detail_id')
    )
    group_total = Decimal('0')
    for r in [parent] + splits:
        group_total += (r.journal_amont or Decimal('0')) + (r.journal_tax or Decimal('0'))

    expected = None
    if parent.amount is not None:
        # 税込金額: 外税(kbn=1)は amount+消費税、内税は amount そのもの
        base = parent.amount + (parent.consumption_tax or Decimal('0')) \
            if parent.consumption_kbn == 1 else parent.amount
        # 外貨は換算レートで円換算（レート未入力なら比較不能として None のまま）
        tsuka = (parent.document.tsuka_cd or '').strip()
        if tsuka and tsuka != '00':
            try:
                fx = Decimal(str(parent.journal_fx_rate or '').replace(',', ''))
                expected = (base * fx).quantize(Decimal('1'))
            except InvalidOperation:
                expected = None
        else:
            expected = base.quantize(Decimal('1'))

    has_split = bool(splits)
    mismatch = bool(has_split and expected is not None and group_total != expected)
    return {
        'has_split':   has_split,
        'group_total': str(group_total),
        'expected':    str(expected) if expected is not None else '',
        'mismatch':    mismatch,
    }
```

`journal_save` 本体を修正:

1. 取得行（5595行目）を差し替え:

```python
    content = get_object_or_404(T_DocumentContent.all_objects, pk=pk)
    is_split = content.split_from_id is not None
```

2. `content.hojo_cd = ...` の直前に借方科目更新を追加:

```python
    # 分割行のみ借方科目の変更を受け付ける（元行は申請どおり固定）
    if is_split:
        acd = request.POST.get('account_cd', '').strip()
        if acd and M_Account.objects.filter(account_cd=acd).exists():
            content.account_id = acd
```

3. `_parse_decimal` 群の直後（`required_checks` の前）に貸方クリアを追加:

```python
    if is_split:
        # 貸方は元行に税込全額を残すため、分割行では常に空にする
        content.account_cd_cre          = None
        content.account_sub_cd_cre      = None
        content.journal_tori_cd_cre     = None
        content.journal_discription_cre = None
        content.journal_amount_cre      = None
        content.journal_amont_fx_cre    = None
```

4. `required_checks`（5627行目）を分岐化:

```python
    required_checks = [
        ('journal_amont',           '税抜金額（借方）', content.journal_amont is not None),
        ('consumption_tax',         '消費税（借方）',   content.journal_tax is not None),
        ('journal_tax_kbn',         '税区分',           bool(content.journal_tax_kbn)),
        ('journal_tax_rate',        '税率',             bool(content.journal_tax_rate)),
        ('journal_discription_deb', '借方適用',         bool(content.journal_discription_deb)),
    ]
    if not is_split:
        required_checks += [
            ('account_cd_cre',          '貸方科目',         bool(content.account_cd_cre)),
            ('journal_amount_cre',      '貸方税抜金額',     content.journal_amount_cre is not None),
            ('journal_discription_cre', '貸方摘要',         bool(content.journal_discription_cre)),
        ]
```

5. `content.save(update_fields=[...])` のリストに科目を条件付きで含める。既存の `content.save(...)` 呼び出しを次に差し替え:

```python
    update_fields = [
        'hojo_cd', 'journal_amont', 'journal_tax',
        'journal_tax_kbn', 'journal_tax_rate',
        'journal_amont_fx', 'journal_tax_fx',
        'journal_fx_rate', 'journal_discription_deb',
        'account_cd_cre', 'account_sub_cd_cre',
        'journal_amount_cre', 'journal_amont_fx_cre',
        'journal_tori_cd_cre', 'journal_discription_cre',
        'journal_done',
    ]
    if is_split:
        update_fields.append('account')
    content.save(update_fields=update_fields)
```

6. レスポンスにグループ情報を追加:

```python
    group_parent = content.split_from if is_split else content
    return JsonResponse({
        'ok': True,
        'journal_done': content.journal_done,
        'missing': missing,
        'group': _journal_group_totals(group_parent),
    })
```

- [ ] **Step 4: テストが通ることを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split -v 2 --keepdb`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py expenses/test_journal_split.py
git commit -m "feat: journal_saveを分割行対応（貸方不要・科目変更・グループ合計チェック）"
```

---

### Task 5: journal_detail_api の分割対応

**Files:**
- Modify: `expenses/views.py`（`journal_detail_api`: 5267-5586行）
- Test: `expenses/test_journal_split.py`

**Interfaces:**
- Consumes: Task 4 の `_journal_group_totals`。
- Produces: レスポンスに `'is_split'`, `'parent_pk'`, `'account_cd_raw'`, `'group'` キー追加。`?account_cd=XXX` クエリで補助科目候補の科目を上書き可能（Task 7 のJSが科目変更時に使用）。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_journal_split.py` に追加:

```python
class JournalDetailApiSplitTest(JournalSplitFixtureMixin, TestCase):
    """journal_detail_api の分割行対応テスト"""

    def setUp(self):
        self.client.force_login(self.user)
        self.split = self._create_split()

    def test_split_detail_flags(self):
        res = self.client.get(f'/settings/settlement/journal/{self.split.pk}/')
        self.assertEqual(res.status_code, 200)
        d = res.json()
        self.assertTrue(d['is_split'])
        self.assertEqual(d['parent_pk'], self.parent.pk)
        self.assertEqual(d['account_cd_raw'], '670')

    def test_split_ref_amount_comes_from_parent(self):
        """分割行の参照エリアには元行の申請金額を表示する"""
        res = self.client.get(f'/settings/settlement/journal/{self.split.pk}/')
        d = res.json()
        self.assertTrue(d['ref']['amount'].startswith('11000'))
        self.assertTrue(d['ref']['consumption_tax'].startswith('1000'))

    def test_split_manual_defaults_are_empty(self):
        """分割行の手入力エリアデフォルトは空（金額は手入力前提）"""
        res = self.client.get(f'/settings/settlement/journal/{self.split.pk}/')
        d = res.json()
        self.assertEqual(d['default_journal_amont'], '')

    def test_parent_detail_is_not_split(self):
        res = self.client.get(f'/settings/settlement/journal/{self.parent.pk}/')
        d = res.json()
        self.assertFalse(d['is_split'])
        self.assertTrue(d['group']['has_split'])

    def test_hojo_options_account_cd_override(self):
        """?account_cd= で補助科目候補の科目を切り替えられる"""
        from expenses.models import M_AccountSub
        M_AccountSub.objects.get_or_create(
            account_cd='671', sub_account_cd='01',
            defaults={'sub_account_name': 'テスト補助'},
        )
        res = self.client.get(
            f'/settings/settlement/journal/{self.split.pk}/?account_cd=671')
        d = res.json()
        self.assertEqual(d['hojo_options'][0]['cd'], '01')
```

※ `M_AccountSub` のフィールド名が異なる場合（`pr_kbn` 必須等）は `expenses/models.py` の定義を確認して合わせる。

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split.JournalDetailApiSplitTest -v 2 --keepdb`
Expected: FAIL（分割行が404、`is_split` キーなし）

- [ ] **Step 3: journal_detail_api を修正**

1. 取得（5270行目）を差し替え:

```python
    content = get_object_or_404(
        T_DocumentContent.all_objects.select_related(
            'document', 'document__man_number', 'document__bumon_cd', 'account',
            'split_from',
        ),
        pk=pk,
    )
    base = content.split_from or content   # 申請金額・添付は元行を参照する
```

2. 添付取得（5288行目）: `att = content.attachments.first()` → `att = base.attachments.first()`

3. 補助科目候補（5309行目）を差し替え:

```python
    # 補助科目候補（?account_cd= が来たらその科目で検索 — 分割行の科目変更時に使用）
    hojo_acd = request.GET.get('account_cd', '').strip() or raw_acd
    hojo_options = list(
        M_AccountSub.objects.filter(account_cd=hojo_acd)
        .order_by('sub_account_cd')
        .values('sub_account_cd', 'sub_account_name')
    )
```

4. `ref` の金額2項目（5529, 5534行目）を base 参照に変更:

```python
            'amount':             str(base.amount or ''),
            ...
            'consumption_tax':    str(base.consumption_tax or ''),
```

5. レスポンス末尾（`'default_discription_cre'` の後）にキー追加:

```python
        'is_split':        content.split_from_id is not None,
        'parent_pk':       content.split_from_id,
        'account_cd_raw':  raw_acd,
        'group':           _journal_group_totals(base),
```

※ 手入力エリアのデフォルト計算（`_c_amount = content.amount` 等）は**変更しない**。分割行は `amount=None` のためデフォルトが自然に空になる（仕様どおり手入力前提）。

- [ ] **Step 4: テストが通ることを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split -v 2 --keepdb`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py expenses/test_journal_split.py
git commit -m "feat: journal_detail_apiを分割行対応（元行参照・補助科目切替・グループ情報）"
```

---

### Task 6: journal_entry ビューの分割対応（並び順・科目選択肢）

**Files:**
- Modify: `expenses/views.py`（`journal_entry`: 5194-5263行）
- Test: `expenses/test_journal_split.py`

**Interfaces:**
- Produces: `rows` の各要素に `'is_split'`, `'parent_pk'` キー追加（分割行は元行の直後に並ぶ）。コンテキストに `account_options`（`[{'account_cd', 'account_name'}]`）追加。分割行の `'amount'` は `journal_amont`。Task 7 のテンプレートが使用。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_journal_split.py` に追加:

```python
class JournalEntryViewSplitTest(JournalSplitFixtureMixin, TestCase):
    """journal_entry ビューの分割行対応テスト"""

    def setUp(self):
        self.client.force_login(self.user)
        self.split = self._create_split()

    def test_split_rows_follow_parent(self):
        """?ids= に元行だけ指定しても分割行が直後に並ぶ"""
        res = self.client.get(
            f'/settings/settlement/journal/entry/?ids={self.parent.pk}')
        self.assertEqual(res.status_code, 200)
        rows = res.context['rows']
        pks = [r['pk'] for r in rows]
        self.assertEqual(pks.index(self.split.pk), pks.index(self.parent.pk) + 1)
        by_pk = {r['pk']: r for r in rows}
        self.assertTrue(by_pk[self.split.pk]['is_split'])
        self.assertEqual(by_pk[self.split.pk]['parent_pk'], self.parent.pk)
        self.assertFalse(by_pk[self.parent.pk]['is_split'])

    def test_account_options_in_context(self):
        res = self.client.get(
            f'/settings/settlement/journal/entry/?ids={self.parent.pk}')
        cds = [a['account_cd'] for a in res.context['account_options']]
        self.assertIn('670', cds)
        self.assertIn('671', cds)

    def test_total_includes_splits(self):
        res = self.client.get(
            f'/settings/settlement/journal/entry/?ids={self.parent.pk}')
        self.assertEqual(res.context['total'], 2)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split.JournalEntryViewSplitTest -v 2 --keepdb`
Expected: FAIL（分割行が rows に含まれない / `account_options` なし）

- [ ] **Step 3: journal_entry を修正**

1. `contents = list(qs)`（5213行目）を差し替え。`qs` はデフォルトマネージャのまま（=元行のみ取得）とし、分割行を後から差し込む:

```python
    parents = list(qs)   # objects マネージャ → 元行のみ

    # 分割行を取得して元行の直後に差し込む
    splits_map = {}
    split_qs = (
        T_DocumentContent.all_objects
        .filter(split_from_id__in=[p.document_detail_id for p in parents])
        .select_related('document', 'document__man_number', 'document__bumon_cd', 'account')
        .order_by('document_detail_id')
    )
    for s in split_qs:
        splits_map.setdefault(s.split_from_id, []).append(s)

    contents = []
    for p in parents:
        contents.append(p)
        contents.extend(splits_map.get(p.document_detail_id, []))
```

2. `rows.append({...})`（5232行目）のループ内に分割用キーを追加。分割行の金額表示は仕訳入力値を使う:

```python
        is_split = c.split_from_id is not None
        rows.append({
            'pk':           c.document_detail_id,
            'document_id':  c.document.document_id,
            'account_name': c.account.account_name if c.account else '',
            'date':         c.date,
            'applicant':    str(c.document.man_number) if c.document.man_number else '',
            'amount':       c.journal_amont if is_split else c.amount,
            'purpose':      c.purpose or '',
            'settle_kbn':   c.settle_kbn or '',
            'settle_label': _JOURNAL_KBN_LABEL.get(c.settle_kbn, c.settle_kbn or ''),
            'journal_done': c.journal_done,
            'warn':         acd5.startswith('??'),
            'is_split':     is_split,
            'parent_pk':    c.split_from_id,
        })
```

3. `render(...)` のコンテキストに科目マスタ全件を追加（`tax_options` の直後で取得）:

```python
    account_options = list(
        M_Account.objects.order_by('account_cd').values('account_cd', 'account_name')
    )
```

```python
        'account_options':       account_options,
```

- [ ] **Step 4: テストが通ることを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split -v 2 --keepdb`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py expenses/test_journal_split.py
git commit -m "feat: journal_entryビューに分割行の並び込みと科目選択肢を追加"
```

---

### Task 7: 仕訳入力テンプレートの分割UI

**Files:**
- Modify: `expenses/templates/expenses/settlement_journal_entry.html`
- Test: `expenses/test_journal_split.py`（レンダリングのスモークテスト）+ 手動確認

**Interfaces:**
- Consumes: Task 3 のAPI（`journal_split` / `journal_split_delete`）、Task 5 のレスポンスキー（`is_split`, `account_cd_raw`, `group`）、Task 6 の `rows` / `account_options`。

- [ ] **Step 1: 失敗するスモークテストを書く**

`expenses/test_journal_split.py` に追加:

```python
class JournalEntryTemplateSplitTest(JournalSplitFixtureMixin, TestCase):
    """分割UIがテンプレートに含まれることのスモークテスト"""

    def setUp(self):
        self.client.force_login(self.user)
        self.split = self._create_split()

    def test_template_has_split_ui(self):
        res = self.client.get(
            f'/settings/settlement/journal/entry/?ids={self.parent.pk}')
        html = res.content.decode('utf-8')
        self.assertIn('jnlSplit(', html)          # 分割ボタン
        self.assertIn('jnlSplitDelete(', html)    # 削除ボタン
        self.assertIn('inp-account-cd', html)     # 借方科目セレクト
        self.assertIn('jnl-cre-section', html)    # 貸方セクションのラッパ
        self.assertIn('↳ 分割', html)             # 分割行のインジケータ
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split.JournalEntryTemplateSplitTest -v 2 --keepdb`
Expected: FAIL

- [ ] **Step 3: テンプレートを修正 — 左ペイン（明細一覧）**

`settlement_journal_entry.html` の CSS ブロック（`.jnl-badge-warn` 定義の後、134行目付近）に追加:

```css
/* ── 分割行 ── */
.jnl-item-split { padding-left: 28px; background: #fafcff; }
.jnl-item-split.done { background: #f0fdf4; }
.jnl-split-tag { color: var(--primary); font-weight: 700; margin-right: 3px; }
.jnl-row-btn {
  border: 1px solid var(--line-strong); background: #fff; color: var(--sub);
  border-radius: 4px; font-size: 10px; padding: 1px 6px; cursor: pointer; margin-top: 3px;
}
.jnl-row-btn:hover { background: var(--primary-soft); color: var(--primary); }
.jnl-row-btn-del:hover { background: #fef2f2; color: #dc2626; border-color: #fecaca; }
```

`<li class="jnl-item ...">`（335行目）を分割対応に差し替え:

```html
        <li class="jnl-item {% if r.is_split %}jnl-item-split{% endif %} {% if r.journal_done %}done{% elif r.warn %}warn{% endif %} {% if forloop.first %}active{% endif %}"
            id="jnl-item-{{ r.pk }}"
            data-pk="{{ r.pk }}"
            data-settle-kbn="{{ r.settle_kbn }}"
            data-parent="{{ r.parent_pk|default_if_none:'' }}"
            onclick="jnlSelect({{ r.pk }})">
          <span class="jnl-item-no">{{ r.document_id }}</span>
          <div style="min-width:0;">
            <div class="jnl-item-name">{% if r.is_split %}<span class="jnl-split-tag">↳ 分割</span>{% endif %}{{ r.account_name }}</div>
            <div class="jnl-item-sub">{{ r.applicant }} ／ {{ r.date|date:"Y/m/d" }}</div>
            <div class="jnl-item-sub" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ r.purpose }}</div>
            <div style="margin-top:3px;">
              {% if r.journal_done %}
                <span class="jnl-badge jnl-badge-done">✔ 入力済</span>
              {% elif r.warn %}
                <span class="jnl-badge jnl-badge-warn">⚠ 要確認</span>
              {% else %}
                <span class="jnl-badge jnl-badge-todo">未入力</span>
              {% endif %}
            </div>
          </div>
          <div style="text-align:right;flex-shrink:0;">
            <div class="jnl-item-amount">{% if r.amount %}¥{{ r.amount|floatformat:"0" }}{% endif %}</div>
            <div class="jnl-item-sub" style="font-size:10px;">{{ r.settle_label }}</div>
            {% if r.is_split %}
            <button type="button" class="jnl-row-btn jnl-row-btn-del"
                    onclick="event.stopPropagation(); jnlSplitDelete({{ r.pk }});">
              <i class="fas fa-times"></i> 削除
            </button>
            {% else %}
            <button type="button" class="jnl-row-btn"
                    onclick="event.stopPropagation(); jnlSplit({{ r.pk }});">
              <i class="fas fa-code-branch"></i> 分割
            </button>
            {% endif %}
          </div>
        </li>
```

- [ ] **Step 4: テンプレートを修正 — 中ペイン（入力フォーム）**

「借方補助科目」の入力行（409行目 `jnl-input-row` の最初）の**直前**に借方科目セレクトを追加（通常は非表示、分割行選択時のみ表示）:

```html
        <div class="jnl-input-row" id="row-account-cd" style="display:none;">
          <span class="jnl-lbl">借方科目</span>
          <select class="jnl-ctrl" id="inp-account-cd" style="flex:1;">
            {% for a in account_options %}
            <option value="{{ a.account_cd }}">{{ a.account_cd }}　{{ a.account_name }}</option>
            {% endfor %}
          </select>
        </div>
```

貸方ブロック全体（468行目の `貸方` 見出し div から、496行目の貸方摘要 `jnl-input-row` の閉じタグまで）を1つの div で包む:

```html
        <div id="jnl-cre-section">
        <!-- 貸方 -->
        ...（既存の貸方見出し + 6つの jnl-input-row をそのまま中に）...
        </div>
```

- [ ] **Step 5: テンプレートを修正 — JS**

定数部（556行目付近）に追加:

```js
  var SPLIT_URL_TPL     = "{% url 'expenses:journal_split' 0 %}".replace('/0/', '/{pk}/');
  var SPLIT_DEL_URL_TPL = "{% url 'expenses:journal_split_delete' 0 %}".replace('/0/', '/{pk}/');
  var currentIsSplit    = false;
```

`populateForm(pk, d)` の末尾（`renderViewer(...)` 呼び出しの前）に追加:

```js
    /* 分割行: 借方科目セレクト表示・貸方非表示 */
    currentIsSplit = !!d.is_split;
    document.getElementById('row-account-cd').style.display = currentIsSplit ? '' : 'none';
    document.getElementById('jnl-cre-section').style.display = currentIsSplit ? 'none' : '';
    if (currentIsSplit) {
      document.getElementById('inp-account-cd').value = d.account_cd_raw || '';
    }
    renderGroupWarn(d.group);
```

新規関数群（`updateListItem` の後に追加）:

```js
  /* ── グループ合計警告 ── */
  function renderGroupWarn(group) {
    var badge = document.getElementById('jnl-form-badge');
    var old = document.getElementById('jnl-group-warn');
    if (old) old.remove();
    if (group && group.mismatch) {
      var span = document.createElement('span');
      span.id = 'jnl-group-warn';
      span.className = 'jnl-badge jnl-badge-warn';
      span.style.marginLeft = '4px';
      span.textContent = '⚠ 分割合計不一致 (' + Number(group.group_total).toLocaleString()
                       + ' / ' + Number(group.expected).toLocaleString() + ')';
      badge.appendChild(span);
    }
  }

  /* ── サマリー件数の増減 ── */
  function bumpTotals(delta) {
    /* サーバーレンダリングの件数表示はページ再読込で正確化されるため、
       ここではリスト件数のみ更新する */
    var countEl = document.getElementById('jnl-list-count');
    if (countEl) {
      var n = parseInt(countEl.textContent) || 0;
      countEl.textContent = (n + delta) + '件';
    }
  }

  /* ── 分割作成 ── */
  window.jnlSplit = function (pk) {
    fetch(SPLIT_URL_TPL.replace('{pk}', pk), {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'csrfmiddlewaretoken=' + encodeURIComponent(CSRF),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { alert(d.error || '分割に失敗しました。'); return; }
        insertSplitItem(d.row);
        bumpTotals(1);
        jnlSelect(d.row.pk);
      });
  };

  function insertSplitItem(row) {
    /* 元行のグループ（元行+既存分割行）の最後の li の後に挿入する */
    var anchor = document.getElementById('jnl-item-' + row.parent_pk);
    if (!anchor) return;
    var next = anchor.nextElementSibling;
    while (next && next.dataset.parent === String(row.parent_pk)) {
      anchor = next;
      next = next.nextElementSibling;
    }
    var li = document.createElement('li');
    li.className = 'jnl-item jnl-item-split';
    li.id = 'jnl-item-' + row.pk;
    li.dataset.pk = row.pk;
    li.dataset.settleKbn = row.settle_kbn;
    li.dataset.parent = String(row.parent_pk);
    li.onclick = function () { jnlSelect(row.pk); };
    li.innerHTML =
      '<span class="jnl-item-no">' + row.document_id + '</span>' +
      '<div style="min-width:0;">' +
        '<div class="jnl-item-name"><span class="jnl-split-tag">↳ 分割</span>' + escapeHtml(row.account_name) + '</div>' +
        '<div class="jnl-item-sub">' + escapeHtml(row.applicant) + ' ／ ' + (row.date || '') + '</div>' +
        '<div class="jnl-item-sub" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + escapeHtml(row.purpose) + '</div>' +
        '<div style="margin-top:3px;"><span class="jnl-badge jnl-badge-todo">未入力</span></div>' +
      '</div>' +
      '<div style="text-align:right;flex-shrink:0;">' +
        '<div class="jnl-item-amount"></div>' +
        '<div class="jnl-item-sub" style="font-size:10px;">' + escapeHtml(row.settle_label) + '</div>' +
        '<button type="button" class="jnl-row-btn jnl-row-btn-del"><i class="fas fa-times"></i> 削除</button>' +
      '</div>';
    li.querySelector('.jnl-row-btn-del').addEventListener('click', function (e) {
      e.stopPropagation();
      jnlSplitDelete(row.pk);
    });
    anchor.insertAdjacentElement('afterend', li);
  }

  function escapeHtml(s) {
    var div = document.createElement('div');
    div.textContent = s || '';
    return div.innerHTML;
  }

  /* ── 分割削除 ── */
  window.jnlSplitDelete = function (pk) {
    if (!confirm('この分割行を削除しますか？入力済みの仕訳値も失われます。')) return;
    fetch(SPLIT_DEL_URL_TPL.replace('{pk}', pk), {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'csrfmiddlewaretoken=' + encodeURIComponent(CSRF),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { alert(d.error || '削除に失敗しました。'); return; }
        var li = document.getElementById('jnl-item-' + pk);
        var parentPk = li ? parseInt(li.dataset.parent) : null;
        if (li) li.remove();
        bumpTotals(-1);
        if (currentPk === pk && parentPk) jnlSelect(parentPk);
      });
  };
```

`jnlSave` の `body` に借方科目を追加（`hojo_cd:` の行の直前）:

```js
      account_cd:             (currentIsSplit ? document.getElementById('inp-account-cd').value : ''),
```

`jnlSave` の成功ハンドラに group 警告更新を追加（`updateListItem(currentPk, d.journal_done);` の直後）:

```js
        renderGroupWarn(d.group);
```

借方科目変更時に補助科目候補を再取得（IIFE末尾の「初期選択」の前に追加）:

```js
  /* ── 分割行の借方科目変更 → 補助科目候補を再取得 ── */
  var accountSel = document.getElementById('inp-account-cd');
  if (accountSel) {
    accountSel.addEventListener('change', function () {
      if (!currentPk || !currentIsSplit) return;
      fetch(DETAIL_URL_TPL.replace('{pk}', currentPk) + '?account_cd=' + encodeURIComponent(this.value))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var hojoSel = document.getElementById('inp-hojo');
          hojoSel.innerHTML = '<option value="">— 選択してください —</option>';
          (d.hojo_options || []).forEach(function (h) {
            var opt = document.createElement('option');
            opt.value = h.cd;
            opt.textContent = h.cd + '　' + h.name;
            hojoSel.appendChild(opt);
          });
        });
    });
  }
```

- [ ] **Step 6: スモークテストが通ることを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split -v 2 --keepdb`
Expected: PASS（全クラス）

- [ ] **Step 7: 手動確認（開発サーバー）**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py runserver 0.0.0.0:8000`（バックグラウンド起動）

ブラウザで `/settings/settlement/journal/entry/` を開き、以下を確認:
1. 元行に「分割」ボタンが表示される
2. 分割ボタン → 直下に「↳ 分割」行が追加され選択状態になる
3. 分割行選択時: 借方科目セレクトが表示され、貸方セクションが消える
4. 分割行に借方値のみ入力して保存 → 「✔ 入力済」になる
5. 合計が合わないとき「⚠ 分割合計不一致」バッジが表示される
6. 分割行の「削除」→ 確認ダイアログ → 行が消え元行が選択される
7. 元行選択時: 借方科目セレクト非表示・貸方セクション表示（従来どおり）

確認後サーバーを停止。

- [ ] **Step 8: コミット**

```bash
git add expenses/templates/expenses/settlement_journal_entry.html expenses/test_journal_split.py
git commit -m "feat: 仕訳入力画面に分割・削除UI（科目選択・貸方非表示・合計警告）を追加"
```

---

### Task 8: journal_csv の分割対応（対象抽出・並び順）

**Files:**
- Modify: `expenses/views.py`（`journal_csv`: 5711-5815行）
- Test: `expenses/test_journal_split.py`

**Interfaces:**
- Consumes: Task 2 の `v_journaldocuments.split_from_id` 列。
- Produces: Excel出力に分割行が「元行の直後」の順で含まれる。`?ids=` に元行だけ指定しても入力済みの分割行を自動包含。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_journal_split.py` に追加:

```python
class JournalCsvSplitTest(JournalSplitFixtureMixin, TestCase):
    """journal_csv（Excel出力）の分割行対応テスト"""

    def setUp(self):
        self.client.force_login(self.user)
        # 元行: 入力済み（借方+貸方）
        self.parent.journal_amont = Decimal('7000')
        self.parent.journal_tax = Decimal('700')
        self.parent.journal_tax_kbn = '312'
        self.parent.journal_tax_rate = '10%'
        self.parent.journal_discription_deb = '元行適用'
        self.parent.account_cd_cre = '41400'
        self.parent.journal_amount_cre = Decimal('11000')
        self.parent.journal_discription_cre = '貸方摘要'
        self.parent.journal_done = True
        self.parent.save()
        # 分割行: 入力済み（借方のみ・科目変更あり）
        self.split = self._create_split(
            account=self.account2,
            journal_amont=Decimal('3000'), journal_tax=Decimal('300'),
            journal_tax_kbn='312', journal_tax_rate='10%',
            journal_discription_deb='分割適用', journal_done=True,
        )

    def _load_rows(self, res):
        from io import BytesIO
        import openpyxl
        wb = openpyxl.load_workbook(BytesIO(res.content))
        ws = wb.active
        return list(ws.iter_rows(min_row=2, values_only=True))

    def test_split_row_included_after_parent(self):
        """元行のidだけ指定しても分割行が直後に出力される"""
        res = self.client.get(
            f'/settings/settlement/journal/csv/?ids={self.parent.pk}')
        self.assertEqual(res.status_code, 200)
        data = self._load_rows(res)
        # 列2 = 申請明細番号（document_detail_id）
        detail_ids = [row[2] for row in data]
        self.assertEqual(detail_ids, [self.parent.pk, self.split.pk])

    def test_split_row_uses_own_account(self):
        res = self.client.get(
            f'/settings/settlement/journal/csv/?ids={self.parent.pk},{self.split.pk}')
        data = self._load_rows(res)
        # 列10 = 科目名。分割行は変更後の科目（交際費）
        self.assertEqual(data[1][10], '交際費')
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split.JournalCsvSplitTest -v 2 --keepdb`
Expected: FAIL（分割行が出力に含まれない）

- [ ] **Step 3: journal_csv を修正**

1. 対象抽出（5729-5738行）を差し替え。`Q` は views.py 冒頭で import 済みか確認し、なければ `from django.db.models import Q` を既存 import 行に追加:

```python
    qs = (
        T_DocumentContent.all_objects
        .filter(settle_kbn__in=journal_kbns, document__status_cd_id='FNS', journal_done=True)
    )
    if selected_ids:
        # 元行のidだけ指定された場合でも、その分割行を自動的に含める
        qs = qs.filter(
            Q(document_detail_id__in=selected_ids) | Q(split_from_id__in=selected_ids)
        )
    detail_ids = list(
        qs.order_by('document__document_type_id', 'document__document_id', 'date')
          .values_list('document_detail_id', flat=True)
    )
```

2. SQL の ORDER BY（5781行目）を変更（分割行を元行の直後に並べる）:

```python
        sql = (
            f"SELECT {', '.join(COLUMNS)} FROM v_journaldocuments "
            f"WHERE document_detail_id IN ({placeholders}) "
            f"ORDER BY document_id, COALESCE(split_from_id, document_detail_id), document_detail_id"
        )
```

- [ ] **Step 4: テストが通ることを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split -v 2 --keepdb`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py expenses/test_journal_split.py
git commit -m "feat: 仕訳Excel出力に分割行を包含（元行直後に出力・自動選択）"
```

---

### Task 9: 仕訳出力一覧（settlement_journal）の分割対応

**Files:**
- Modify: `expenses/views.py`（`settlement_journal`: 5169-5190行）
- Modify: `expenses/templates/expenses/settlement_journal.html`
- Test: `expenses/test_journal_split.py`

**Interfaces:**
- Consumes: Task 1 の `all_objects`。
- Produces: 一覧に分割行が元行直後に表示され、チェックボックスは元行と連動（分割行側は disabled）。分割行が未入力のグループは一覧から除外。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_journal_split.py` に追加:

```python
class SettlementJournalListSplitTest(JournalSplitFixtureMixin, TestCase):
    """仕訳出力一覧の分割行対応テスト"""

    def setUp(self):
        self.client.force_login(self.user)
        self.parent.journal_done = True
        self.parent.save()

    def test_done_split_follows_parent(self):
        split = self._create_split(journal_done=True)
        res = self.client.get('/settings/settlement/journal/')
        rows = res.context['rows']
        pks = [r['content'].pk for r in rows]
        self.assertEqual(pks.index(split.pk), pks.index(self.parent.pk) + 1)
        by_pk = {r['content'].pk: r for r in rows}
        self.assertTrue(by_pk[split.pk]['is_split'])

    def test_group_with_undone_split_excluded(self):
        """分割行が未入力のグループは（不完全な仕訳のため）一覧に出さない"""
        self._create_split(journal_done=False)
        res = self.client.get('/settings/settlement/journal/')
        pks = [r['content'].pk for r in res.context['rows']]
        self.assertNotIn(self.parent.pk, pks)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split.SettlementJournalListSplitTest -v 2 --keepdb`
Expected: FAIL

- [ ] **Step 3: settlement_journal ビューを修正**

`settlement_journal`（5169-5190行）の本体を差し替え:

```python
@login_required
def settlement_journal(request):
    """仕訳出力: 仕訳入力済み(journal_done=1)の明細一覧から対象を選んでExcel出力する"""
    journal_kbns = list(_JOURNAL_KBN_LABEL.keys())
    parents = list(
        T_DocumentContent.objects
        .select_related('document', 'document__document_type', 'document__man_number', 'document__bumon_cd', 'account')
        .filter(settle_kbn__in=journal_kbns, document__status_cd_id='FNS', journal_done=True)
        .order_by('document__document_type_id', 'document__document_id', 'date')
    )

    # 分割行を取得（journal_done は問わず取得し、未入力があるグループは除外する）
    splits_map = {}
    split_qs = (
        T_DocumentContent.all_objects
        .filter(split_from_id__in=[p.document_detail_id for p in parents])
        .select_related('document', 'document__document_type', 'account')
        .order_by('document_detail_id')
    )
    for s in split_qs:
        splits_map.setdefault(s.split_from_id, []).append(s)

    rows = []
    for p in parents:
        splits = splits_map.get(p.document_detail_id, [])
        if any(not s.journal_done for s in splits):
            continue   # 分割行が未入力 → グループごと出力対象外
        for c in [p] + splits:
            rows.append({
                'content':      c,
                'settle_label': _JOURNAL_KBN_LABEL.get(c.settle_kbn, c.settle_kbn),
                'journal_done': c.journal_done,
                'is_split':     c.split_from_id is not None,
                'parent_pk':    c.split_from_id,
            })
    return render(request, 'expenses/settlement_journal.html', {
        'rows':    rows,
        'current': 'settlement_journal',
    })
```

- [ ] **Step 4: settlement_journal.html を修正**

明細行（52-85行）の変更点:

1. 申請件名セル（62行目）に分割インジケータ:

```html
            <td>{% if row.is_split %}<span style="color:var(--primary);font-weight:700;">↳ 分割</span> {% endif %}{{ c.document.title }}</td>
```

2. 金額セル（65-67行目）: 分割行は仕訳借方金額を表示:

```html
            <td class="text-end text-nowrap">
              {% if row.is_split %}
                {% if c.journal_amont %}{{ c.journal_amont|floatformat:"0" }}{% else %}-{% endif %}
              {% elif c.amount %}{{ c.amount|floatformat:"0" }}{% else %}-{% endif %}
            </td>
```

3. チェックボックス（77-81行目）を差し替え（分割行は disabled で元行と連動）:

```html
              <input type="checkbox"
                     class="form-check-input journal-check"
                     value="{{ c.document_detail_id }}"
                     data-done="{{ row.journal_done|yesno:'true,false' }}"
                     data-parent="{{ row.parent_pk|default_if_none:'' }}"
                     {% if row.is_split %}disabled{% endif %}
                     {% if row.journal_done %}checked{% endif %}>
```

4. `<script>` 内: 連動処理を追加。`getChecks()` の定義の後に:

```js
  /* 分割行のチェックを元行と連動させる（分割行は disabled、選択は常に元行経由） */
  function syncSplitChecks() {
    var state = {};
    getChecks().forEach(function (c) {
      if (!c.dataset.parent) state[c.value] = c.checked;
    });
    getChecks().forEach(function (c) {
      if (c.dataset.parent && c.dataset.parent in state) {
        c.checked = state[c.dataset.parent];
      }
    });
  }

  getChecks().forEach(function (c) {
    if (!c.dataset.parent) c.addEventListener('change', syncSplitChecks);
  });
```

5. 既存の全選択/入力済のみ選択/全解除の各ハンドラ末尾に `syncSplitChecks();` を追加。

※ `checkedIds()` は disabled チェックボックスも `checked` を読めるため変更不要（分割行のidも `?ids=` に含まれる）。

- [ ] **Step 5: テストが通ることを確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses.test_journal_split -v 2 --keepdb`
Expected: PASS

- [ ] **Step 6: 既存テスト全体のリグレッション確認**

Run: `wsl -d Ubuntu-24.04 --cd /home/idc_user/expense_project2 -- .venv/bin/python manage.py test expenses -v 1 --keepdb`
Expected: PASS（全テスト）

- [ ] **Step 7: コミット**

```bash
git add expenses/views.py expenses/templates/expenses/settlement_journal.html expenses/test_journal_split.py
git commit -m "feat: 仕訳出力一覧に分割行を表示・元行チェックと連動"
```

---

### Task 10: ドキュメント更新

**Files:**
- Modify: `CLAUDE.md`（精算処理セクションの後）
- Modify: `docs/superpowers/specs/2026-07-06-journal-split-design.md`（migration 番号修正）

- [ ] **Step 1: CLAUDE.md に機能の説明を追加**

「### 精算処理 (`/settings/settlement/`)」セクションの末尾に追加:

```markdown
### 仕訳明細の分割（split_from）

仕訳入力画面で1明細を複数の勘定科目・税区分に分割できる。

- `T_DocumentContent.split_from`: 自己参照FK（NULL=通常明細、非NULL=分割行）。migration 0097
- **デフォルトマネージャ `objects` は分割行を除外**（`split_from__isnull=True`）。申請側の画面・CSV・合計は無改修で分割行が見えない。仕訳系ビューは `all_objects` を使う
- **注意: `parent.splits.all()` は逆参照にもデフォルトマネージャのフィルタが継承されるため常に空。** 分割行の取得は `T_DocumentContent.all_objects.filter(split_from=parent)` を使うこと
- 分割行は `amount`/`consumption_tax` が NULL（申請金額は元行に不変）。仕訳金額は手入力
- 分割行のみ借方科目変更可（`journal_save` の POST `account_cd`）。貸方は元行に税込全額を残し、分割行の貸方は常に空・必須チェック対象外
- API: `POST /settings/settlement/journal/<pk>/split/`（作成）、`POST .../delete/`（分割行のみ削除可）
- 合計チェック: `_journal_group_totals()` が元行+分割行の借方合計と元行税込金額を比較し `mismatch` を返す（警告表示のみ、保存はブロックしない）
- `v_documentcontents` / `v_journaldocuments` に `split_from_id` 列あり（migration 0098）。Excel出力は元行直後に分割行を並べる
```

- [ ] **Step 2: 仕様書の migration 番号を修正**

`docs/superpowers/specs/2026-07-06-journal-split-design.md` 内の「migration 0088」を「migration 0097」に修正（2箇所: セクション 1-1 の見出しと本文）。

- [ ] **Step 3: コミット**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-07-06-journal-split-design.md
git commit -m "docs: 仕訳分割機能をCLAUDE.mdに追記、仕様書のmigration番号を修正"
```
