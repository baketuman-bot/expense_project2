# 伝票日付を精算開始日(settled_at)基準に変更する Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 仕訳作成・債務管理データ作成画面の伝票日付を、明細日付(`T_DocumentContent.date`)から精算開始日(`T_Document.settled_at`)基準に変更し、精算開始日を設定する起点として「未精算データ分類」画面を申請単位のリストに作り直す。

**Architecture:** `T_DocumentContent` に `voucher_date` プロパティ（`document.settled_at or self.date`）を追加し、仕訳系の全表示箇所（一覧・参照API・出力一覧・CSV用SQLビュー）をこのプロパティ（またはSQL上の同等ロジック）経由に置き換える。`settled_at` の書き込みタイミングを「精算完了時」から「未精算データ分類での精算開始時」に一本化するため、既存の2箇所（`_settlement_payment_view` の確定処理、`settlement_toggle`）で行われている `settled_at` の上書きを削除する。

**Tech Stack:** Django 5.2.6 / Python 3.12 / MySQL 8.0（本番相当）。テストは Django `TestCase`（`test_expense_db` を使用。既存 `expenses/test_journal_split.py` と同じ構成）。

## Global Constraints

- 本プロジェクトは本番DB (`expense_db`) を直接使って開発している。`DELETE`/`TRUNCATE`/`DROP` 等の破壊的操作、`python manage.py flush` は禁止。
- `python manage.py test` 実行時は `DJANGO_TEST_DB_NAME=expense_db` を絶対に指定しないこと（デフォルトの `test_expense_db` を使う）。
- マイグレーションは `AddField`/`AlterField` など非破壊的な操作のみ。データを削除するマイグレーションは作らない。
- モデル命名規則: マスタ `M_` prefix、トランザクション `T_` prefix、ビュー `V_` prefix（`expenses/view_sqls.py` で定義、`create_views` management command 経由で適用）。
- コメント・ラベルは日本語。

---

## Task 1: `voucher_date` プロパティの追加と `settled_at` の意味変更（models.py）

**Files:**
- Modify: `expenses/models.py:537`（`T_Document.settled_at` フィールド定義）
- Modify: `expenses/models.py:719-720`（`T_DocumentContent` に `voucher_date` プロパティ追加、`__str__` の直前）
- Test: `expenses/test_voucher_date.py`（新規）
- Migration: `expenses/migrations/0100_settled_at_help_text.py`（`makemigrations` で自動生成）

**Interfaces:**
- Produces: `T_DocumentContent.voucher_date`（プロパティ、型 `datetime.date | None`）— Task 5, 6, 7 が使用する。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_voucher_date.py` を新規作成:

```python
"""voucher_date プロパティ（伝票日付の精算開始日フォールバック）のテスト"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class VoucherDateFixtureMixin:
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
        cls.user, _ = User.objects.get_or_create(
            man_number='VD001',
            defaults={'username': 'voucher_date_user', 'user_name': '伝票太郎'},
        )


class VoucherDatePropertyTest(VoucherDateFixtureMixin, TestCase):
    def test_uses_settled_at_when_set(self):
        doc = T_Document.objects.create(
            document_type=self.doc_type, title='精算開始日あり', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 10, 0, 0, 0),
        )
        content = T_DocumentContent.objects.create(
            document=doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn='CAS_INPRO',
        )
        self.assertEqual(content.voucher_date, datetime.date(2026, 7, 10))

    def test_falls_back_to_content_date_when_settled_at_none(self):
        doc = T_Document.objects.create(
            document_type=self.doc_type, title='精算開始日なし', man_number=self.user,
            status_cd=self.status_fns, settled_at=None,
        )
        content = T_DocumentContent.objects.create(
            document=doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn='CAS_INPRO',
        )
        self.assertEqual(content.voucher_date, datetime.date(2026, 7, 1))
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python manage.py test expenses.test_voucher_date -v 2`
Expected: FAIL — `AttributeError: 'T_DocumentContent' object has no attribute 'voucher_date'`

- [ ] **Step 3: 最小限の実装を行う**

`expenses/models.py:537` を変更（`T_Document.settled_at` フィールド定義）:

```python
    is_settled = models.BooleanField("精算完了", default=False, db_column='is_settled')
    settled_at = models.DateTimeField(
        "精算開始日時", null=True, blank=True, db_column='settled_at',
        help_text='精算処理を開始した日（未精算データ分類画面で設定）。精算完了日ではない。',
    )
```

`expenses/models.py` の `T_DocumentContent` クラス内、`__str__` の直前（719-720行目付近）にプロパティを追加:

```python
    objects     = DocumentContentManager()  # 分割行を除外（申請側の既定）
    all_objects = models.Manager()          # 全件（仕訳系ビュー専用）

    # 旧フィールド（receipt/receipt_thumbnail）廃止に伴い、サムネイル生成や save の上書きは不要

    @property
    def voucher_date(self):
        """伝票日付: 精算開始日(document.settled_at)があればそれを優先、なければ明細日付にフォールバック"""
        settled_at = self.document.settled_at
        if settled_at is None:
            return self.date
        return settled_at.date() if hasattr(settled_at, 'date') else settled_at

    def __str__(self):
        return f"{self.document_detail_id} - {self.purpose or ''}"
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python manage.py test expenses.test_voucher_date -v 2`
Expected: PASS (2 tests)

- [ ] **Step 5: マイグレーションを生成**

Run: `python manage.py makemigrations expenses -n settled_at_help_text`
Expected: `expenses/migrations/0100_settled_at_help_text.py` が生成される（`AlterField` のみ、DBスキーマへの実質的な変更なし）

- [ ] **Step 6: マイグレーションを適用し確認**

Run: `python manage.py migrate expenses`
Expected: `Applying expenses.0100_settled_at_help_text... OK`

- [ ] **Step 7: コミット**

```bash
git add expenses/models.py expenses/test_voucher_date.py expenses/migrations/0100_settled_at_help_text.py
git commit -m "feat: T_DocumentContentにvoucher_dateプロパティを追加、settled_atの意味を精算開始日に変更"
```

---

## Task 2: `_settlement_payment_view` の `settled_at` 上書きを削除

**Files:**
- Modify: `expenses/views.py:4972-4976`
- Test: `expenses/test_settled_at_semantics.py`（新規、Task 3 も同ファイルに追記）

**Interfaces:**
- Consumes: なし（既存ビューの修正のみ）

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_settled_at_semantics.py` を新規作成:

```python
"""settled_at(精算開始日)が精算完了処理や手動トグルで上書きされないことのテスト"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class SettledAtFixtureMixin:
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
        cls.user, _ = User.objects.get_or_create(
            man_number='SA001',
            defaults={'username': 'settled_at_user', 'user_name': '精算太郎'},
        )


class SettlementPaymentViewSettledAtTest(SettledAtFixtureMixin, TestCase):
    """現金精算処理(本社)確定時にsettled_atが上書きされないこと"""

    def setUp(self):
        self.client.force_login(self.user)
        self.pre_settled_at = datetime.datetime(2026, 7, 1, 0, 0, 0)
        self.doc = T_Document.objects.create(
            document_type=self.doc_type, title='現金精算テスト', man_number=self.user,
            status_cd=self.status_fns, pay_kbn='03', settled_at=self.pre_settled_at,
        )
        self.content = T_DocumentContent.objects.create(
            document=self.doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn='CAS_PRE',
        )

    def test_confirm_does_not_overwrite_settled_at(self):
        res = self.client.post('/settings/settlement/cash/hq/', {
            'action': 'confirm',
            'selected_ids': [str(self.content.pk)],
            'settle_ymd': '2026-07-15',
        })
        self.assertEqual(res.status_code, 302)
        self.doc.refresh_from_db()
        self.content.refresh_from_db()
        self.assertTrue(self.doc.is_settled)
        self.assertEqual(self.doc.settled_at, self.pre_settled_at)   # 上書きされていない
        self.assertEqual(self.content.settle_kbn, 'CAS_INPRO')
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python manage.py test expenses.test_settled_at_semantics -v 2`
Expected: FAIL — `AssertionError` (`self.doc.settled_at` が `2026-07-15` に上書きされているため `self.pre_settled_at` と一致しない)

- [ ] **Step 3: 最小限の実装を行う**

`expenses/views.py:4964-4976` を変更:

```python
                doc_ids = {c.document_id for c in target_contents}
                for doc_id in doc_ids:
                    has_remaining = T_DocumentContent.objects.filter(
                        document_id=doc_id
                    ).filter(
                        Q(settle_kbn__isnull=True) |
                        Q(settle_kbn__endswith='_PRE')
                    ).exists()
                    if not has_remaining:
                        T_Document.objects.filter(document_id=doc_id).update(
                            is_settled=True,
                        )
```

（`settled_at=settle_ymd` の指定を削除。`is_settled=True` の更新のみ残す）

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python manage.py test expenses.test_settled_at_semantics -v 2`
Expected: PASS (1 test)

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py expenses/test_settled_at_semantics.py
git commit -m "fix: 精算完了処理でsettled_at(精算開始日)を上書きしないよう修正"
```

---

## Task 3: `settlement_toggle` の `settled_at` 操作を削除

**Files:**
- Modify: `expenses/views.py:6173-6185`
- Test: `expenses/test_settled_at_semantics.py`（Task 2で作成したファイルに追記）

**Interfaces:**
- Consumes: なし

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_settled_at_semantics.py` の末尾に追記:

```python
class SettlementToggleSettledAtTest(SettledAtFixtureMixin, TestCase):
    """精算処理画面の手動トグルがsettled_atを変更しないこと"""

    def setUp(self):
        self.client.force_login(self.user)
        self.pre_settled_at = datetime.datetime(2026, 7, 1, 0, 0, 0)
        self.doc = T_Document.objects.create(
            document_type=self.doc_type, title='トグルテスト', man_number=self.user,
            status_cd=self.status_fns, is_settled=False, settled_at=self.pre_settled_at,
        )

    def test_toggle_on_does_not_change_settled_at(self):
        res = self.client.post(f'/settings/settlement/{self.doc.pk}/toggle/')
        self.assertEqual(res.status_code, 200)
        self.doc.refresh_from_db()
        self.assertTrue(self.doc.is_settled)
        self.assertEqual(self.doc.settled_at, self.pre_settled_at)

    def test_toggle_off_does_not_clear_settled_at(self):
        self.doc.is_settled = True
        self.doc.save(update_fields=['is_settled'])
        res = self.client.post(f'/settings/settlement/{self.doc.pk}/toggle/')
        self.assertEqual(res.status_code, 200)
        self.doc.refresh_from_db()
        self.assertFalse(self.doc.is_settled)
        self.assertEqual(self.doc.settled_at, self.pre_settled_at)   # クリアされない
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python manage.py test expenses.test_settled_at_semantics.SettlementToggleSettledAtTest -v 2`
Expected: FAIL（`test_toggle_on_does_not_change_settled_at` で `settled_at` が `tz.now()` に変わっているため不一致。`test_toggle_off_does_not_clear_settled_at` で `settled_at` が `None` になっているため不一致）

- [ ] **Step 3: 最小限の実装を行う**

`expenses/views.py:6173-6185` を変更:

```python
@login_required
def settlement_toggle(request, pk):
    """精算完了フラグをトグル（AJAX POST）"""
    doc = get_object_or_404(T_Document, pk=pk, status_cd__status_cd='FNS')
    doc.is_settled = not doc.is_settled
    doc.save(update_fields=['is_settled'])
    return JsonResponse({
        'is_settled': doc.is_settled,
        'settled_at': doc.settled_at.strftime('%Y/%m/%d %H:%M') if doc.settled_at else '',
    })
```

（`doc.settled_at = tz.now() if doc.is_settled else None` の行を削除。`import datetime` / `from django.utils import timezone as tz` のローカルimportがこの関数内で他に使われていなければ削除してよいが、他で使っていないため関数内の `from django.utils import timezone as tz` と `import json` は不要なら削除する）

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python manage.py test expenses.test_settled_at_semantics -v 2`
Expected: PASS (3 tests: Task2の1件 + 本Taskの2件)

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py expenses/test_settled_at_semantics.py
git commit -m "fix: 精算処理画面の手動トグルがsettled_at(精算開始日)を変更しないよう修正"
```

---

## Task 4: 「未精算データ分類」画面を申請単位に再設計

**Files:**
- Modify: `expenses/views.py:4864-4927`（`settlement_classify` ビュー全体を置き換え）
- Modify: `expenses/templates/expenses/settlement_classify.html`（全体を置き換え）
- Test: `expenses/test_settlement_classify.py`（新規）

**Interfaces:**
- Consumes: `T_DocumentContent.objects`（分割行除外デフォルトマネージャ）、`M_Item(data_kbn='PAY')`
- Produces: `settlement_classify` ビューが `POST` で `T_DocumentContent.settle_kbn` を一括付与し `T_Document.settled_at` をセットする（Task 5, 6, 7 が読む値の発生源）

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_settlement_classify.py` を新規作成:

```python
"""未精算データ分類画面（申請単位リスト化）のテスト"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Item, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class SettlementClassifyFixtureMixin:
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
        cls.user, _ = User.objects.get_or_create(
            man_number='SC001',
            defaults={'username': 'settlement_classify_user', 'user_name': '分類太郎'},
        )
        M_Item.objects.get_or_create(
            data_kbn='PAY', key='03',
            defaults={'content': '現金(本社)', 'content2': 'CAS_PRE', 'content3': '11110'},
        )
        M_Item.objects.get_or_create(
            data_kbn='PAY', key='01',
            defaults={'content': '給与振込', 'content2': 'SAL_PRE', 'content3': '41430'},
        )


class SettlementClassifyGetTest(SettlementClassifyFixtureMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.user)
        self.doc = T_Document.objects.create(
            document_type=self.doc_type, title='現金精算申請', man_number=self.user,
            status_cd=self.status_fns, pay_kbn='03',
        )
        T_DocumentContent.objects.create(
            document=self.doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn=None,
        )
        T_DocumentContent.objects.create(
            document=self.doc, date=datetime.date(2026, 7, 2), account=self.account,
            amount=Decimal('2000'), settle_kbn=None,
        )

    def test_groups_by_document_and_sums_unclassified_amount(self):
        res = self.client.get('/settings/settlement/classify/')
        self.assertEqual(res.status_code, 200)
        rows = res.context['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['document'].document_id, self.doc.document_id)
        self.assertEqual(rows[0]['total_amount'], Decimal('3000'))
        self.assertEqual(rows[0]['method_label'], '現金（本社）')

    def test_classified_lines_excluded_from_total(self):
        T_DocumentContent.objects.filter(document=self.doc, amount=Decimal('2000')).update(
            settle_kbn='CAS_INPRO'
        )
        res = self.client.get('/settings/settlement/classify/')
        rows = res.context['rows']
        self.assertEqual(rows[0]['total_amount'], Decimal('1000'))   # 分類済みの2000円は除外

    def test_mixed_methods_within_document_shows_both_labels(self):
        """1申請内に現金明細と法人カード明細が混在する場合、両方の精算方法を表示する"""
        mixed_doc = T_Document.objects.create(
            document_type=self.doc_type, title='混在申請', man_number=self.user,
            status_cd=self.status_fns, pay_kbn='03',
        )
        T_DocumentContent.objects.create(
            document=mixed_doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn=None,
        )
        T_DocumentContent.objects.create(
            document=mixed_doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('500'), settle_kbn=None, corpo_card=2, corpo_card_no='9999',
        )
        res = self.client.get('/settings/settlement/classify/')
        rows = {r['document'].document_id: r for r in res.context['rows']}
        labels = set(rows[mixed_doc.pk]['method_label'].split(' / '))
        self.assertEqual(labels, {'現金（本社）', 'カード'})


class SettlementClassifyPostTest(SettlementClassifyFixtureMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.user)
        self.cash_doc = T_Document.objects.create(
            document_type=self.doc_type, title='現金精算申請', man_number=self.user,
            status_cd=self.status_fns, pay_kbn='03',
        )
        self.cash_content = T_DocumentContent.objects.create(
            document=self.cash_doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn=None,
        )
        self.card_content = T_DocumentContent.objects.create(
            document=self.cash_doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('500'), settle_kbn=None, corpo_card=2, corpo_card_no='1234',
        )

    def test_post_assigns_settle_kbn_per_line_and_sets_settled_at(self):
        res = self.client.post('/settings/settlement/classify/', {
            'selected_doc_ids': [str(self.cash_doc.pk)],
            'settle_ymd': '2026-07-20',
        })
        self.assertEqual(res.status_code, 302)
        self.cash_content.refresh_from_db()
        self.card_content.refresh_from_db()
        self.cash_doc.refresh_from_db()
        # 行ごとの自動判定: pay_kbn='03' の通常行はCAS_PRE、カード行はCOC_PRE
        self.assertEqual(self.cash_content.settle_kbn, 'CAS_PRE')
        self.assertEqual(self.card_content.settle_kbn, 'COC_PRE')
        self.assertEqual(self.cash_doc.settled_at.date(), datetime.date(2026, 7, 20))

    def test_unchecked_document_not_affected(self):
        other_doc = T_Document.objects.create(
            document_type=self.doc_type, title='対象外申請', man_number=self.user,
            status_cd=self.status_fns, pay_kbn='01',
        )
        other_content = T_DocumentContent.objects.create(
            document=other_doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('100'), settle_kbn=None,
        )
        self.client.post('/settings/settlement/classify/', {
            'selected_doc_ids': [str(self.cash_doc.pk)],
            'settle_ymd': '2026-07-20',
        })
        other_content.refresh_from_db()
        other_doc.refresh_from_db()
        self.assertIsNone(other_content.settle_kbn)
        self.assertIsNone(other_doc.settled_at)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python manage.py test expenses.test_settlement_classify -v 2`
Expected: FAIL — `KeyError: 'document'`（現行の `rows` は `{'content': c, 'default_status_cd': ...}` のままで `'document'`/`'total_amount'`/`'method_label'` キーが無い）。POSTテストは既存の `selected_ids`/`settle_kbn_{id}` を前提とした実装のため `settled_at` が更新されず失敗する。

- [ ] **Step 3: 最小限の実装を行う**

`expenses/views.py:4863-4927` を丸ごと置き換え:

```python
@login_required
def settlement_classify(request):
    """未精算データ分類: 申請単位で未分類明細をまとめ、精算方法の自動判定表示・精算開始日の設定を行う"""
    import datetime

    PAY_KBN_TO_STATUS_CD = {
        item.key: item.content2
        for item in M_Item.objects.filter(data_kbn='PAY').exclude(content2='')
    }
    PAY_KBN_LABEL = {
        '01': '給与',
        '02': '現金（大阪）',
        '03': '現金（本社）',
        '04': '振込',
    }

    def _default_status_cd(content):
        if content.corpo_card_no:
            return 'COC_PRE'
        return PAY_KBN_TO_STATUS_CD.get(content.document.pay_kbn or '', '')

    def _method_label(content):
        if content.corpo_card_no:
            return 'カード'
        return PAY_KBN_LABEL.get(content.document.pay_kbn or '', '-')

    stl_filter      = request.GET.get('stl_filter', '')
    pay_kbn_filter  = request.GET.get('pay_kbn', '')

    if request.method == 'POST':
        selected_doc_ids = request.POST.getlist('selected_doc_ids')
        settle_ymd_str = request.POST.get('settle_ymd', '').strip()
        try:
            settle_ymd = datetime.date.fromisoformat(settle_ymd_str)
        except (ValueError, TypeError):
            settle_ymd = datetime.date.today()

        if selected_doc_ids:
            target_contents = list(
                T_DocumentContent.objects
                .filter(document_id__in=selected_doc_ids, settle_kbn__isnull=True)
                .select_related('document')
            )
            for c in target_contents:
                c.settle_kbn = _default_status_cd(c)
            T_DocumentContent.objects.bulk_update(target_contents, ['settle_kbn'])
            T_Document.objects.filter(document_id__in=selected_doc_ids).update(
                settled_at=settle_ymd,
            )

        qs = request.GET.urlencode()
        redirect_url = reverse('expenses:settlement_classify')
        if qs:
            redirect_url += '?' + qs
        return redirect(redirect_url)

    contents = (
        T_DocumentContent.objects
        .select_related('document', 'document__document_type')
        .filter(settle_kbn__isnull=True, document__status_cd_id='FNS')
        .order_by('document__document_type_id', 'document_id', 'date')
    )

    if stl_filter == 'COC_PRE':
        contents = contents.exclude(corpo_card_no__isnull=True).exclude(corpo_card_no='')
    elif stl_filter:
        matching_pay_kbns = [k for k, v in PAY_KBN_TO_STATUS_CD.items() if v == stl_filter]
        contents = contents.filter(
            document__pay_kbn__in=matching_pay_kbns
        ).filter(Q(corpo_card_no__isnull=True) | Q(corpo_card_no=''))
    if pay_kbn_filter:
        contents = contents.filter(document__pay_kbn=pay_kbn_filter)

    docs = {}
    for c in contents:
        entry = docs.setdefault(c.document_id, {
            'document':      c.document,
            'total_amount':  Decimal('0'),
            'method_labels': {},   # 挿入順を保持する順序付きセットとして使う（dictのkeys）
        })
        if c.amount:
            entry['total_amount'] += c.amount
        entry['method_labels'][_method_label(c)] = True

    rows = []
    for entry in docs.values():
        entry['method_label'] = ' / '.join(entry['method_labels'].keys())
        rows.append(entry)

    stl_statuses = list(M_Status.objects.filter(status_kbn='STL').order_by('order_by'))
    pay_items    = list(M_Item.objects.filter(data_kbn='PAY').order_by('key'))

    return render(request, 'expenses/settlement_classify.html', {
        'rows': rows,
        'stl_statuses': stl_statuses,
        'pay_items': pay_items,
        'stl_filter': stl_filter,
        'pay_kbn_filter': pay_kbn_filter,
        'today': datetime.date.today().isoformat(),
        'current': 'settlement_classify',
    })
```

`expenses/templates/expenses/settlement_classify.html` を丸ごと置き換え:

```html
{% extends "expenses/base.html" %}

{% block content %}
<div class="mt-4" style="max-width:1200px;">

  <div class="page-head mb-3">
    <h2 class="page-title mb-0">
      <span class="pt-ico"><i class="fas fa-tags"></i></span>
      未精算データ分類
    </h2>
    <div class="page-actions">
      <a href="{% url 'expenses:settlement_menu' %}" class="btn btn-sm btn-outline-secondary">
        <i class="fas fa-arrow-left me-1"></i>精算処理メニューへ
      </a>
    </div>
  </div>

  <!-- 検索フォーム -->
  <form method="get" class="card card-body py-3 mb-3">
    <div class="row g-2 align-items-end">
      <div class="col-md-3">
        <label class="form-label small mb-1">精算方法</label>
        <select name="stl_filter" class="form-select form-select-sm">
          <option value="">すべて</option>
          {% for s in stl_statuses %}
          <option value="{{ s.status_cd }}" {% if stl_filter == s.status_cd %}selected{% endif %}>{{ s.status_name }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-md-3">
        <label class="form-label small mb-1">精算申請</label>
        <select name="pay_kbn" class="form-select form-select-sm">
          <option value="">すべて</option>
          {% for item in pay_items %}
          <option value="{{ item.key }}" {% if pay_kbn_filter == item.key %}selected{% endif %}>{{ item.content }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-auto">
        <button type="submit" class="btn btn-sm btn-primary">
          <i class="fas fa-search me-1"></i>絞り込む
        </button>
        {% if stl_filter or pay_kbn_filter %}
        <a href="{% url 'expenses:settlement_classify' %}" class="btn btn-sm btn-outline-secondary ms-1">
          <i class="fas fa-times me-1"></i>クリア
        </a>
        {% endif %}
      </div>
    </div>
  </form>

  {% if rows %}
  <form method="post" action="?{{ request.GET.urlencode }}">
    {% csrf_token %}

    <div class="d-flex align-items-center gap-3 mb-2 flex-wrap">
      <span class="text-muted small">{{ rows|length }} 件</span>
      <a href="#" id="select-all" class="small">全選択</a>
      <a href="#" id="deselect-all" class="small">全解除</a>

      <span class="vr mx-1"></span>
      <label class="form-label small mb-0 text-nowrap" for="settle_ymd">精算日</label>
      <input type="date" id="settle_ymd" name="settle_ymd"
             class="form-control form-control-sm" style="width:auto;"
             value="{{ today }}">

      <button type="submit" class="btn btn-primary btn-sm ms-auto">
        <i class="fas fa-check me-1"></i>チェック済を精算開始
      </button>
    </div>

    <div class="card">
      <div class="table-responsive">
        <table class="table table-hover mb-0 small">
          <thead>
            <tr>
              <th class="text-nowrap">申請ID</th>
              <th class="text-nowrap">申請種別</th>
              <th>申請件名</th>
              <th>申請者</th>
              <th class="text-end text-nowrap">明細合計金額</th>
              <th class="text-nowrap">精算方法</th>
              <th class="text-center text-nowrap">精算開始</th>
            </tr>
          </thead>
          <tbody>
            {% for row in rows %}
            {% with doc=row.document %}
            <tr class="classify-row">
              <td class="text-nowrap">
                <a href="{% url 'expenses:expense_detail' doc.document_id %}?from=settlement_classify">
                  {{ doc.document_id }}
                </a>
              </td>
              <td class="text-nowrap">{{ doc.document_type.document_type_name }}</td>
              <td>{{ doc.title }}</td>
              <td class="text-nowrap">{{ doc.man_number }}</td>
              <td class="text-end text-nowrap">{{ row.total_amount|floatformat:"0" }}</td>
              <td class="text-nowrap">{{ row.method_label }}</td>
              <td class="text-center">
                <input type="checkbox"
                       class="form-check-input classify-check"
                       name="selected_doc_ids"
                       value="{{ doc.document_id }}">
              </td>
            </tr>
            {% endwith %}
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <div class="mt-2 d-flex justify-content-end">
      <button type="submit" class="btn btn-primary btn-sm">
        <i class="fas fa-check me-1"></i>チェック済を精算開始
      </button>
    </div>
  </form>

  {% else %}
  <div class="card">
    <div class="card-body text-center text-muted py-5">
      <i class="fas fa-check-circle fa-2x mb-2 d-block" style="color:var(--primary);"></i>
      未分類の明細データはありません。
    </div>
  </div>
  {% endif %}

</div>

<script>
(function () {
  const selectAll = document.getElementById('select-all');
  const deselectAll = document.getElementById('deselect-all');

  function getChecks() {
    return document.querySelectorAll('.classify-check');
  }

  if (selectAll) {
    selectAll.addEventListener('click', function (e) {
      e.preventDefault();
      getChecks().forEach(function (c) { c.checked = true; });
    });
  }
  if (deselectAll) {
    deselectAll.addEventListener('click', function (e) {
      e.preventDefault();
      getChecks().forEach(function (c) { c.checked = false; });
    });
  }
})();
</script>
{% endblock %}
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python manage.py test expenses.test_settlement_classify -v 2`
Expected: PASS (4 tests)

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py expenses/templates/expenses/settlement_classify.html expenses/test_settlement_classify.py
git commit -m "feat: 未精算データ分類画面を申請単位に再設計し精算開始日フォームを追加"
```

---

## Task 5: 仕訳作成/債務管理データ作成入力画面の伝票日付を`voucher_date`に変更

**Files:**
- Modify: `expenses/views.py:5367`（`_journal_entry_view` 一覧行）
- Modify: `expenses/views.py:5683`（`journal_detail_api`）
- Test: `expenses/test_journal_voucher_date.py`（新規）

**Interfaces:**
- Consumes: `T_DocumentContent.voucher_date`（Task 1）

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_journal_voucher_date.py` を新規作成:

```python
"""仕訳作成入力画面・参照APIの伝票日付がvoucher_dateを使うことのテスト"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class JournalEntryVoucherDateTest(TestCase):
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
        cls.user, _ = User.objects.get_or_create(
            man_number='JE001',
            defaults={'username': 'journal_entry_user', 'user_name': '入力太郎'},
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.doc = T_Document.objects.create(
            document_type=self.doc_type, title='仕訳入力テスト', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 20, 0, 0, 0),
        )
        self.content = T_DocumentContent.objects.create(
            document=self.doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn='CAS_INPRO',
        )

    def test_entry_list_uses_voucher_date(self):
        res = self.client.get(f'/settings/settlement/journal/entry/?ids={self.content.pk}')
        self.assertEqual(res.status_code, 200)
        rows = res.context['rows']
        self.assertEqual(rows[0]['date'], datetime.date(2026, 7, 20))

    def test_detail_api_uses_voucher_date(self):
        res = self.client.get(f'/settings/settlement/journal/{self.content.pk}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['ref']['date'], '2026-07-20')
```

`journal_detail_api` の実URLパスは `expenses/urls.py:78` の `settings/settlement/journal/<int:pk>/`（`/detail/` サフィックスは無い）。

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python manage.py test expenses.test_journal_voucher_date -v 2`
Expected: FAIL — `rows[0]['date']` が `datetime.date(2026, 7, 1)`（明細日付のまま）で `2026-07-20` と不一致。API側も `'2026-07-01'` で不一致。

- [ ] **Step 3: 最小限の実装を行う**

`expenses/views.py:5367` を変更:

```python
            'date':         c.voucher_date,
```

`expenses/views.py:5683` を変更:

```python
            'date':               content.voucher_date.strftime('%Y-%m-%d') if content.voucher_date else '',
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python manage.py test expenses.test_journal_voucher_date -v 2`
Expected: PASS (2 tests)

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py expenses/test_journal_voucher_date.py
git commit -m "feat: 仕訳作成入力画面・参照APIの伝票日付をvoucher_date(精算開始日)基準に変更"
```

---

## Task 6: 仕訳出力/債務管理出力一覧の伝票日付を`voucher_date`に変更

**Files:**
- Modify: `expenses/templates/expenses/settlement_journal.html:41`（見出し）、`:61`（`c.date` → `c.voucher_date`）
- Test: `expenses/test_journal_voucher_date.py`（Task 5で作成したファイルに追記）

**Interfaces:**
- Consumes: `T_DocumentContent.voucher_date`（Task 1）

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_journal_voucher_date.py` の末尾に追記:

```python
class JournalOutputVoucherDateTest(TestCase):
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
        cls.user, _ = User.objects.get_or_create(
            man_number='JO001',
            defaults={'username': 'journal_output_user', 'user_name': '出力太郎'},
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.doc = T_Document.objects.create(
            document_type=self.doc_type, title='仕訳出力テスト', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 25, 0, 0, 0),
        )
        T_DocumentContent.objects.create(
            document=self.doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn='CAS_INPRO', journal_done=True,
        )

    def test_output_list_shows_voucher_date(self):
        res = self.client.get('/settings/settlement/journal/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '2026/07/25')
        self.assertNotContains(res, '2026/07/01')
```

`datetime` と `Decimal` は既に Task 5 のインポートで足りているので追加インポート不要。

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python manage.py test expenses.test_journal_voucher_date.JournalOutputVoucherDateTest -v 2`
Expected: FAIL — レスポンスに `2026/07/01`（明細日付）が含まれ `2026/07/25` は含まれない

- [ ] **Step 3: 最小限の実装を行う**

`expenses/templates/expenses/settlement_journal.html:41` を変更:

```html
            <th class="text-nowrap">伝票日付</th>
```

`expenses/templates/expenses/settlement_journal.html:61` を変更:

```html
            <td class="text-nowrap">{{ c.voucher_date|date:"Y/m/d" }}</td>
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python manage.py test expenses.test_journal_voucher_date -v 2`
Expected: PASS (3 tests: Task5の2件 + 本Taskの1件)

- [ ] **Step 5: コミット**

```bash
git add expenses/templates/expenses/settlement_journal.html expenses/test_journal_voucher_date.py
git commit -m "feat: 仕訳出力/債務管理出力一覧の伝票日付表示をvoucher_date基準に変更"
```

---

## Task 7: `v_journaldocuments` SQLビューの伝票日付をsettled_at基準に変更（CSV出力用）

**Files:**
- Modify: `expenses/view_sqls.py:232`（`_V_JOURNALDOCUMENTS`）
- Test: `expenses/test_journal_voucher_date.py`（Task 5/6で作成したファイルに追記。ビュー文字列アサーション + CSV出力の実行時テスト）
- Migration: `expenses/migrations/0101_update_v_journaldocuments_settled_at.py`（新規）

**Interfaces:**
- Consumes: `T_Document.settled_at`, `T_DocumentContent.date`（SQLレベル）

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_journal_voucher_date.py` の末尾に追記:

```python
class ViewSqlVoucherDateTest(TestCase):
    def test_v_journaldocuments_uses_settled_at_with_fallback(self):
        from expenses.view_sqls import _V_JOURNALDOCUMENTS
        self.assertIn('COALESCE(DATE(vdc.settled_at), vdc.date) AS date', _V_JOURNALDOCUMENTS)


class JournalCsvVoucherDateTest(TestCase):
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
        cls.user, _ = User.objects.get_or_create(
            man_number='JC001',
            defaults={'username': 'journal_csv_user', 'user_name': 'CSV太郎'},
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.doc = T_Document.objects.create(
            document_type=self.doc_type, title='CSV出力テスト', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 28, 0, 0, 0),
        )
        self.content = T_DocumentContent.objects.create(
            document=self.doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn='CAS_INPRO', journal_done=True,
        )

    def test_csv_output_uses_voucher_date(self):
        res = self.client.get(f'/settings/settlement/journal/csv/?ids={self.content.pk}')
        self.assertEqual(res.status_code, 200)
        body = b''.join(res.streaming_content).decode('utf-8-sig')
        self.assertIn('2026-07-28', body)
        self.assertNotIn('2026-07-01', body)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python manage.py test expenses.test_journal_voucher_date.ViewSqlVoucherDateTest expenses.test_journal_voucher_date.JournalCsvVoucherDateTest -v 2`
Expected: FAIL — `ViewSqlVoucherDateTest` は文字列不一致で失敗。`JournalCsvVoucherDateTest` はCSV本文に `2026-07-01` が含まれ `2026-07-28` が含まれないため失敗。

- [ ] **Step 3: 最小限の実装を行う**

`expenses/view_sqls.py:232` を変更:

```python
  COALESCE(DATE(vdc.settled_at), vdc.date) AS date,
```

（元の `vdc.date,` を置き換え）

新規マイグレーション `expenses/migrations/0101_update_v_journaldocuments_settled_at.py` を作成:

```python
from django.db import migrations

from expenses.view_sqls import _V_JOURNALDOCUMENTS

_OLD_V_JOURNALDOCUMENTS = _V_JOURNALDOCUMENTS.replace(
    'COALESCE(DATE(vdc.settled_at), vdc.date) AS date,',
    'vdc.date,',
)


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0100_settled_at_help_text'),
    ]

    operations = [
        migrations.RunSQL(
            sql=_V_JOURNALDOCUMENTS,
            reverse_sql=_OLD_V_JOURNALDOCUMENTS,
        ),
    ]
```

- [ ] **Step 4: マイグレーションを適用**

Run: `python manage.py migrate expenses`
Expected: `Applying expenses.0101_update_v_journaldocuments_settled_at... OK`

- [ ] **Step 5: テストを実行して成功を確認**

Run: `python manage.py test expenses.test_journal_voucher_date -v 2`
Expected: PASS（Task5,6,7合計6テスト）

- [ ] **Step 6: `create_views` management command との整合性を確認**

Run: `python manage.py create_views --dry-run` が存在すれば実行して差分がないことを確認。無ければ `expenses/management/commands/create_views.py` を開き、`view_sqls.VIEW_SQLS` を辞書経由で参照している（ハードコードされた別のSQL文字列を持っていない）ことを目視確認する。

- [ ] **Step 7: コミット**

```bash
git add expenses/view_sqls.py expenses/migrations/0101_update_v_journaldocuments_settled_at.py expenses/test_journal_voucher_date.py
git commit -m "feat: v_journaldocumentsビューの伝票日付をsettled_at基準に変更(CSV出力対応)"
```

---

## 最終確認（全Task完了後）

- [ ] **Step 1: 全テストスイートを実行**

Run: `python manage.py test expenses.test_voucher_date expenses.test_settled_at_semantics expenses.test_settlement_classify expenses.test_journal_voucher_date -v 2`
Expected: 全件PASS

- [ ] **Step 2: 手動確認（開発サーバー）**

Run: `python manage.py runserver`
ブラウザで以下を確認:
1. `/settings/settlement/classify/` — 申請単位のリスト表示、精算方法ラベル、明細合計金額が正しいこと
2. 精算日を入力してチェック済み申請を送信 → 対象申請の明細が分類され、`is_settled` 判定に影響しないこと
3. `/settings/settlement/journal/entry/` — 伝票日付が精算開始日になっていること
4. `/settings/settlement/journal/` → CSV出力し、伝票日付列が精算開始日になっていること
5. `/settings/settlement/debt/entry/`, `/settings/settlement/debt/` でも同様に確認（`_JOURNAL_MODES['debt']` は同じ関数を共有しているため、Task 5,6,7の変更がそのまま適用される）
