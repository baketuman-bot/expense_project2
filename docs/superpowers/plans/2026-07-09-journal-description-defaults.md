# 仕訳作成 摘要デフォルト値変更 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 仕訳作成画面の借方・貸方摘要のデフォルト表示項目・並び順を変更し、40文字を超えたら警告バッジを出す。

**Architecture:** `expenses/views.py` の `journal_detail_api`（`/settings/settlement/journal/<pk>/` GET）が返す `default_discription_deb` / `default_discription_cre` の生成ロジックを差し替える（バックエンド）。あわせて `settlement_journal_entry.html` に、借方摘要・貸方摘要入力欄それぞれの隣に40文字超の警告バッジをJSで表示する処理を追加する（フロントエンド）。

**Tech Stack:** Django 5.2.6 / Python 3.12+, MySQL（ローカル開発）, Django Templates + vanilla JS

## Global Constraints

- 本プロジェクトは本番DB (`expense_db`) を直接使用している。`python manage.py test` は `DJANGO_TEST_DB_NAME` を設定せず、デフォルトの `test_expense_db` を使うこと（`expense_project/settings.py:111` 参照）。
- 破壊的なマイグレーション・`flush`・`DELETE`/`TRUNCATE` は一切行わない（本タスクでは不要）。
- 既存の50文字切り詰め（入力欄 `maxlength="50"` に合わせたバックエンド側 `[:50]`）は変更しない。
- 分割行（`split_from` あり）の貸方摘要は対象外（既存どおり貸方セクション自体が非表示のため、今回のロジック変更の影響を受けない）。

---

### Task 1: 借方摘要のデフォルト値を変更する

**Files:**
- Modify: `expenses/views.py:5631-5645`（`journal_detail_api` 内の借方摘要デフォルト生成部分）
- Test: `expenses/test_journal_description_defaults.py`（新規作成）

**Interfaces:**
- Consumes: `journal_detail_api` が既に計算済みの `raw_acd`（`views.py:5464`, `str(content.account_id or '').strip()`）、`content`（`T_DocumentContent`インスタンス）、`doc`（`content.document`）
- Produces: `_def_desc_deb`（文字列）。この値は既存どおり `JsonResponse` の `default_discription_deb` キーとして返る（`views.py:5772`、変更不要）。Task 2 はこの変数に影響しない別ブロックなので依存なし。

現状のコード（`views.py:5631-5645`）:

```python
    # 借方適用
    _applicant_name = doc.man_number.user_name if doc.man_number else ''
    if raw_acd.strip() == '670':
        _deb_parts = ['旅費特例']
        if content.shiharaisaki:
            _deb_parts.append(content.shiharaisaki)
        if _applicant_name:
            _deb_parts.append(_applicant_name)
    else:
        _deb_parts = []
        if content.purpose:
            _deb_parts.append(content.purpose)
        if content.shiharaisaki:
            _deb_parts.append(content.shiharaisaki)
    _def_desc_deb = ' '.join(_deb_parts)[:50]
```

- [ ] **Step 1: 借方摘要デフォルトのテストファイルを新規作成し、失敗するテストを書く**

`expenses/test_journal_description_defaults.py` を新規作成:

```python
"""仕訳作成のデフォルト摘要（借方・貸方）生成ロジックのテスト"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class JournalDescriptionDefaultsFixtureMixin:
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
        cls.account_travel, _ = M_Account.objects.get_or_create(
            account_cd='670', defaults={'account_name': '旅費交通費'}
        )
        cls.account_other, _ = M_Account.objects.get_or_create(
            account_cd='671', defaults={'account_name': '交際費'}
        )
        cls.user, _ = User.objects.get_or_create(
            man_number='JD001',
            defaults={'username': 'journal_desc_user', 'user_name': '精算太郎'},
        )

    def _make_content(self, account, **extra):
        doc = T_Document.objects.create(
            document_type=self.doc_type, title='摘要デフォルトテスト', man_number=self.user,
            status_cd=self.status_fns,
        )
        defaults = dict(
            document=doc, date=datetime.date(2026, 7, 8), account=account,
            amount=Decimal('1000'), consumption_kbn=0, settle_kbn='CAS_INPRO',
            purpose='出張', shiharaisaki='JR東日本',
        )
        defaults.update(extra)
        content = T_DocumentContent.objects.create(**defaults)
        return doc, content


class DebitDescriptionDefaultTest(JournalDescriptionDefaultsFixtureMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.user)

    def test_travel_account_prepends_tokuhirei(self):
        doc, content = self._make_content(self.account_travel)
        res = self.client.get(f'/settings/settlement/journal/{content.pk}/')
        self.assertEqual(res.status_code, 200)
        d = res.json()
        self.assertEqual(
            d['default_discription_deb'],
            f'旅費特例 7/8 出張 精算太郎 JR東日本 {doc.document_id}',
        )

    def test_non_travel_account_has_no_prefix(self):
        doc, content = self._make_content(self.account_other)
        res = self.client.get(f'/settings/settlement/journal/{content.pk}/')
        d = res.json()
        self.assertEqual(
            d['default_discription_deb'],
            f'7/8 出張 精算太郎 JR東日本 {doc.document_id}',
        )

    def test_blank_purpose_and_payee_are_skipped_without_double_space(self):
        doc, content = self._make_content(self.account_other, purpose='', shiharaisaki='')
        res = self.client.get(f'/settings/settlement/journal/{content.pk}/')
        d = res.json()
        self.assertEqual(
            d['default_discription_deb'],
            f'7/8 精算太郎 {doc.document_id}',
        )
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `python manage.py test expenses.test_journal_description_defaults.DebitDescriptionDefaultTest -v 2`
Expected: 3件とも FAIL（`default_discription_deb` の値が期待値と一致しない。現状は日付・申請IDが含まれないため）

- [ ] **Step 3: 借方摘要デフォルト生成ロジックを実装する**

`expenses/views.py:5631-5645` を以下に置き換える:

```python
    # 借方摘要: [旅費特例] 月/日(content.date) 目的 精算者名 支払先 申請ID (スペース連結、50文字上限)
    _applicant_name = doc.man_number.user_name if doc.man_number else ''
    _deb_parts = []
    if raw_acd.strip() == '670':
        _deb_parts.append('旅費特例')
    if content.date:
        _deb_parts.append(f'{content.date.month}/{content.date.day}')
    if content.purpose:
        _deb_parts.append(content.purpose)
    if _applicant_name:
        _deb_parts.append(_applicant_name)
    if content.shiharaisaki:
        _deb_parts.append(content.shiharaisaki)
    _deb_parts.append(str(doc.document_id))
    _def_desc_deb = ' '.join(_deb_parts)[:50]
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `python manage.py test expenses.test_journal_description_defaults.DebitDescriptionDefaultTest -v 2`
Expected: 3件とも PASS

- [ ] **Step 5: 既存の仕訳関連テストが壊れていないことを確認する**

Run: `python manage.py test expenses.test_journal_split expenses.test_journal_voucher_date -v 2`
Expected: 全件 PASS（既存の摘要値を直接assertしているテストがないことを確認済みだが、回帰がないことの確認として実行する）

- [ ] **Step 6: コミット**

```bash
git add expenses/views.py expenses/test_journal_description_defaults.py
git commit -m "feat: 仕訳作成の借方摘要デフォルトを日付・目的・精算者名・支払先・申請IDの並びに変更"
```

---

### Task 2: 貸方摘要のデフォルト値を変更する

**Files:**
- Modify: `expenses/views.py:5701-5711`（`journal_detail_api` 内の貸方摘要デフォルト生成部分）
- Test: `expenses/test_journal_description_defaults.py`（Task 1 で作成したファイルに追記）

**Interfaces:**
- Consumes: Task 1 で定義される `_applicant_name`（`views.py:5632` で定義され、この関数スコープ内で Task 2 のブロックからもそのまま参照できる。Task 1 の変更後もこの変数名・意味は変わらない）、`content.corpo_card`（`T_DocumentContent` の `IntegerField`、`models.py:682`）
- Produces: `_def_desc_cre`（文字列）。既存どおり `JsonResponse` の `default_discription_cre` キーとして返る（`views.py:5779`、変更不要）

現状のコード（`views.py:5701-5711`）:

```python
    # 貸方摘要: M/D(申請日) purpose shiharaisaki user_name (スペース連結、50文字上限)
    _cre_parts = []
    if doc.created_at:
        _cre_parts.append(f'{doc.created_at.month}/{doc.created_at.day}')
    if content.purpose:
        _cre_parts.append(content.purpose)
    if content.shiharaisaki:
        _cre_parts.append(content.shiharaisaki)
    if doc.man_number and doc.man_number.user_name:
        _cre_parts.append(doc.man_number.user_name)
    _def_desc_cre = ' '.join(_cre_parts)[:50]
```

- [ ] **Step 1: 貸方摘要デフォルトの失敗するテストを追記する**

`expenses/test_journal_description_defaults.py` の末尾に追記:

```python


class CreditDescriptionDefaultTest(JournalDescriptionDefaultsFixtureMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.user)

    def test_default_includes_settler_name(self):
        doc, content = self._make_content(self.account_other)
        res = self.client.get(f'/settings/settlement/journal/{content.pk}/')
        self.assertEqual(res.status_code, 200)
        d = res.json()
        self.assertEqual(
            d['default_discription_cre'],
            f'7/8 出張 精算太郎 JR東日本 {doc.document_id}',
        )

    def test_corpo_card_excludes_settler_name(self):
        doc, content = self._make_content(
            self.account_other, corpo_card=2, corpo_card_no='1234',
        )
        res = self.client.get(f'/settings/settlement/journal/{content.pk}/')
        d = res.json()
        self.assertEqual(
            d['default_discription_cre'],
            f'7/8 出張 JR東日本 {doc.document_id}',
        )
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `python manage.py test expenses.test_journal_description_defaults.CreditDescriptionDefaultTest -v 2`
Expected: 2件とも FAIL（現状は `doc.created_at` を使っており日付・申請IDも含まれないため）

- [ ] **Step 3: 貸方摘要デフォルト生成ロジックを実装する**

`expenses/views.py:5701-5711` を以下に置き換える:

```python
    # 貸方摘要: 月/日(content.date) 目的 精算者名 支払先 申請ID (法人カード時は精算者名を除く。スペース連結、50文字上限)
    _cre_parts = []
    if content.date:
        _cre_parts.append(f'{content.date.month}/{content.date.day}')
    if content.purpose:
        _cre_parts.append(content.purpose)
    if content.corpo_card != 2 and _applicant_name:
        _cre_parts.append(_applicant_name)
    if content.shiharaisaki:
        _cre_parts.append(content.shiharaisaki)
    _cre_parts.append(str(doc.document_id))
    _def_desc_cre = ' '.join(_cre_parts)[:50]
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `python manage.py test expenses.test_journal_description_defaults -v 2`
Expected: `test_journal_description_defaults.py` 内の全テスト（Task 1 の3件 + Task 2 の2件）が PASS

- [ ] **Step 5: 既存の仕訳関連テスト一式が壊れていないことを確認する**

Run: `python manage.py test expenses.test_journal_split expenses.test_journal_voucher_date expenses.test_voucher_date -v 2`
Expected: 全件 PASS

- [ ] **Step 6: コミット**

```bash
git add expenses/views.py expenses/test_journal_description_defaults.py
git commit -m "feat: 仕訳作成の貸方摘要デフォルトを日付・目的・精算者名・支払先・申請IDの並びに変更し、法人カード時は精算者名を除外"
```

---

### Task 3: 摘要40文字超の警告バッジをフロントエンドに追加する

**Files:**
- Modify: `expenses/templates/expenses/settlement_journal_entry.html:493-496`（借方摘要入力行）
- Modify: `expenses/templates/expenses/settlement_journal_entry.html:525-528`（貸方摘要入力行）
- Modify: `expenses/templates/expenses/settlement_journal_entry.html:692`（借方摘要の値セット直後）
- Modify: `expenses/templates/expenses/settlement_journal_entry.html:702`（貸方摘要の値セット直後）
- Modify: `expenses/templates/expenses/settlement_journal_entry.html:1132-1133` 付近（`input` イベント登録箇所に追記）
- Test: `expenses/test_journal_description_defaults.py`（追記、テンプレートのスモークテスト）

**Interfaces:**
- Consumes: 既存の `.jnl-badge` / `.jnl-badge-warn` CSSクラス（`settlement_journal_entry.html:133` で定義済み）。入力欄ID `inp-jnl-desc-deb` / `inp-cre-desc`（既存, 変更なし）
- Produces: 新しい要素ID `inp-jnl-desc-deb-warn` / `inp-cre-desc-warn`、新しいJS関数 `updateDescWarn(inputId, warnId)`（グローバルではなくスクリプト内のローカル関数でよい。他タスクからは参照されない）

- [ ] **Step 1: バッジ表示のスモークテストを追記する（失敗させる）**

`expenses/test_journal_description_defaults.py` の末尾に追記:

```python


class DescriptionWarnBadgeTemplateTest(JournalDescriptionDefaultsFixtureMixin, TestCase):
    """40文字超警告バッジ用のマークアップ・JSが出力されていることのスモークテスト"""

    def setUp(self):
        self.client.force_login(self.user)

    def test_entry_page_has_warn_badge_markup(self):
        doc, content = self._make_content(self.account_other)
        res = self.client.get(f'/settings/settlement/journal/entry/?ids={content.pk}')
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')
        self.assertIn('inp-jnl-desc-deb-warn', html)
        self.assertIn('inp-cre-desc-warn', html)
        self.assertIn('updateDescWarn', html)
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `python manage.py test expenses.test_journal_description_defaults.DescriptionWarnBadgeTemplateTest -v 2`
Expected: FAIL（`inp-jnl-desc-deb-warn` 等がまだHTMLに存在しない）

- [ ] **Step 3: 借方摘要入力行にバッジ要素を追加する**

`expenses/templates/expenses/settlement_journal_entry.html:493-496` を以下に置き換える:

```html
        <div class="jnl-input-row">
          <span class="jnl-lbl">借方適用</span>
          <input type="text" class="jnl-ctrl" id="inp-jnl-desc-deb" maxlength="50" placeholder="" style="flex:1;">
          <span id="inp-jnl-desc-deb-warn" class="jnl-badge jnl-badge-warn" style="display:none;white-space:nowrap;">40文字以上</span>
        </div>
```

- [ ] **Step 4: 貸方摘要入力行にバッジ要素を追加する**

`expenses/templates/expenses/settlement_journal_entry.html:525-528` を以下に置き換える:

```html
        <div class="jnl-input-row">
          <span class="jnl-lbl">貸方摘要</span>
          <input type="text" class="jnl-ctrl" id="inp-cre-desc" maxlength="50" placeholder="" style="flex:1;">
          <span id="inp-cre-desc-warn" class="jnl-badge jnl-badge-warn" style="display:none;white-space:nowrap;">40文字以上</span>
        </div>
```

- [ ] **Step 5: 警告判定関数を追加し、`input` イベントに紐づける**

`expenses/templates/expenses/settlement_journal_entry.html:1132-1133`（`updateCreSubName` のイベント登録の直後）に以下を追記する:

```javascript
  /* ── 摘要 40文字超の警告バッジ ── */
  function updateDescWarn(inputId, warnId) {
    var input = document.getElementById(inputId);
    var warn  = document.getElementById(warnId);
    if (!input || !warn) return;
    warn.style.display = input.value.length > 40 ? '' : 'none';
  }
  document.getElementById('inp-jnl-desc-deb').addEventListener('input', function () {
    updateDescWarn('inp-jnl-desc-deb', 'inp-jnl-desc-deb-warn');
  });
  document.getElementById('inp-cre-desc').addEventListener('input', function () {
    updateDescWarn('inp-cre-desc', 'inp-cre-desc-warn');
  });
```

- [ ] **Step 6: 明細読み込み時（デフォルト値・保存済み値セット直後）にも警告判定を反映させる**

`expenses/templates/expenses/settlement_journal_entry.html:692` の行:

```javascript
    document.getElementById('inp-jnl-desc-deb').value  = entry.journal_discription_deb  || d.default_discription_deb     || '';
```

の直後に1行追加する:

```javascript
    document.getElementById('inp-jnl-desc-deb').value  = entry.journal_discription_deb  || d.default_discription_deb     || '';
    updateDescWarn('inp-jnl-desc-deb', 'inp-jnl-desc-deb-warn');
```

同様に `expenses/templates/expenses/settlement_journal_entry.html:702` の行:

```javascript
    document.getElementById('inp-cre-desc').value      = entry.journal_discription_cre || d.default_discription_cre  || '';
```

の直後に1行追加する:

```javascript
    document.getElementById('inp-cre-desc').value      = entry.journal_discription_cre || d.default_discription_cre  || '';
    updateDescWarn('inp-cre-desc', 'inp-cre-desc-warn');
```

（`function updateDescWarn(...)` は関数宣言のため、スクリプト内での定義位置に関わらずホイスティングされ、`renderDetail` 内のこの呼び出しから問題なく参照できる。）

- [ ] **Step 7: テストを実行し、成功することを確認する**

Run: `python manage.py test expenses.test_journal_description_defaults -v 2`
Expected: `test_journal_description_defaults.py` 内の全テスト（Task 1〜3、計6件）が PASS

- [ ] **Step 8: 開発サーバーでブラウザ動作確認する**

Run: `python manage.py runserver`

1. `/settings/settlement/journal/entry/?ids=<任意の明細pk>` を開く
2. 借方摘要・貸方摘要の入力欄に41文字以上のテキストを入力し、「40文字以上」バッジが表示されることを確認する
3. 40文字以下に削ると、バッジが消えることを確認する
4. 明細を切り替え（左のリストから別明細をクリック）、デフォルト値または保存済み値が40文字を超えている場合、選択直後からバッジが表示されていることを確認する
5. 借方摘要・貸方摘要それぞれで、実際にデフォルト表示された文字列が Task 1 / Task 2 で定義した並び順（旅費交通費なら「旅費特例」が先頭、法人カード明細なら精算者名が除外）になっていることを目視確認する

- [ ] **Step 9: コミット**

```bash
git add expenses/templates/expenses/settlement_journal_entry.html expenses/test_journal_description_defaults.py
git commit -m "feat: 仕訳作成の摘要入力欄に40文字超の警告バッジを追加"
```
