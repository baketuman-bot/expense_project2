# 固定資産 詳細・承認画面 レイアウト見直し Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 固定資産系申請（`M_DocumentGroup.category='assets'`）の「申請詳細」「承認」「承認管理（管理者）」の3画面で、不要な通貨・合計金額表示を消し、動的フィールドの見出し・テーブル構造のバグを修正し、明細カードを資産画像表示用にカスタマイズする。

**Architecture:** `views.py` に `is_asset` コンテキストフラグを追加し、3つの詳細系ビュー（`expense_detail`/`approval_detail`/`settings_approval_detail`）すべてに渡す。3つのテンプレート（`expense_detail.html`/`approval_detail.html`/`settings_approval_detail.html`）と共有パーシャル（`_expense_detail_display.html`）で `is_asset` を使って表示を出し分ける。動的フィールドテーブルのセクション見出し `colspan` 固定値バグは `is_asset` に関係なく全体的に修正する。

**Tech Stack:** Django 5.2.6 / Python 3.12, Django Template Language, Django TestCase (実DB使用、`--keepdb` 必須)

## Global Constraints

- 対象は `category='assets'` の全DocType（取得・移動・廃棄報告書）。`_is_asset_doc_type(doc_type)`（views.py:57-60、既存）で判定する。
- `colspan` の動的化修正は固定資産以外の動的フィールド画面にも適用される全体修正（`is_asset` 条件なし）。
- それ以外の変更（申請情報の通貨・合計金額非表示、見出し変更、明細カードの出し分け）はすべて `is_asset` の場合のみ適用する。通常の経費申請の表示を一切変更してはならない。
- 計算式 `{oter_amount}` のタイプミス（マスタデータ）の修正は対象外。編集・新規作成フォーム（`expense_form.html`、`_dynamic_fields_section.html`、`_asset_form_context()`）は変更しない。
- テスト実行は本番DB (`expense_db`) を直接破壊してはならない。`python manage.py test` 実行時は `DJANGO_TEST_DB_NAME=expense_db` を絶対に使用しないこと。`--keepdb` を付けて実行する。
- このプロジェクトの Bash 実行環境は Windows Git Bash 経由で `wsl.localhost` UNC パスにアクセスしている。実際の WSL(Ubuntu-24.04) の Python/Django を使うには `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && ...'` でラップすること。

---

## Task 1: 動的フィールドテーブルのセクション見出し colspan 動的化

**Files:**
- Modify: `expenses/views.py:289-296`（`_build_dynamic_fields_display` 関数末尾）
- Test: `expenses/tests.py`（末尾に新規テストクラスを追加）

**Interfaces:**
- Consumes: なし（既存の `_build_dynamic_fields_display(expense)` のロジックのみ変更）
- Produces: `_build_dynamic_fields_display(expense)` が返す `rows` リストの各 `{'type': 'section', ...}` 要素に新キー `'colspan'`（int）を追加する。後続タスクのテンプレートはこの `row.colspan` を参照する。

現在の `expenses/views.py:207-296` の `_build_dynamic_fields_display` 関数の末尾（289-296行目）は以下の通り:

```python
    # 1フィールドのみの行は td_colspan=3（残3列をスパン）、複数は 1
    for row in rows:
        if row['type'] == 'data':
            n = len(row['fields'])
            for f in row['fields']:
                f['td_colspan'] = 3 if n == 1 else 1

    return rows
```

- [ ] **Step 1: 失敗するテストを書く**

`expenses/tests.py` の末尾に以下のテストクラスを追加する:

```python
class BuildDynamicFieldsDisplaySectionColspanTest(TestCase):
    """_build_dynamic_fields_display のセクション見出し行 colspan 動的化を確認する"""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from expenses.models import (
            M_DocumentGroup, M_DocumentType, M_DocumentField, M_Status, T_Document, T_DocumentContent,
        )
        User = get_user_model()
        self.user = User.objects.create_user(
            username='colspan_test_user', man_number='COLSPAN1',
            user_name='colspanテスト', password='pass123',
        )
        self.status, _ = M_Status.objects.get_or_create(
            status_cd='INPRO', defaults={'status_name': '申請中', 'action_name': '提出'}
        )
        self.grp, _ = M_DocumentGroup.objects.get_or_create(
            menu_group='COLSPANGRP', defaults={'menu_group_name': 'colspanテストグループ', 'category': 'expense', 'menu_order': 95},
        )

    def _make_document(self, doc_type, stored_content):
        from expenses.models import T_Document, T_DocumentContent
        doc = T_Document.objects.create(
            document_type=doc_type, title='colspanテスト申請', man_number=self.user, status_cd=self.status,
        )
        T_DocumentContent.objects.create(document=doc, purpose='テスト', amount=1000, content=stored_content)
        return doc

    def test_section_colspan_matches_widest_data_row(self):
        """3フィールドの行を含む場合、セクション見出し行の colspan は 6 になること"""
        from expenses.models import M_DocumentType, M_DocumentField
        from expenses.views import _build_dynamic_fields_display

        doc_type = M_DocumentType.objects.create(document_type_name='colspanテスト種別A', menu_group=self.grp)
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='a', field_name_view='A', field_type='char',
            field_order=1, row_break=False, section_header='',
        )
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='b', field_name_view='B', field_type='char',
            field_order=2, row_break=True, section_header='セクションA',
        )
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='c', field_name_view='C', field_type='char',
            field_order=3, row_break=False, section_header='',
        )
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='d', field_name_view='D', field_type='char',
            field_order=4, row_break=False, section_header='',
        )
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='e', field_name_view='E', field_type='char',
            field_order=5, row_break=True, section_header='セクションB',
        )
        doc = self._make_document(doc_type, {'a': '1', 'b': '2', 'c': '3', 'd': '4', 'e': '5'})

        rows = _build_dynamic_fields_display(doc)

        section_rows = [r for r in rows if r['type'] == 'section']
        self.assertEqual(len(section_rows), 2)
        for r in section_rows:
            self.assertEqual(r['colspan'], 6)

    def test_section_colspan_defaults_to_2_when_all_rows_single_field(self):
        """全データ行が1フィールドのみの場合、セクション見出し行の colspan は 2 になること"""
        from expenses.models import M_DocumentType, M_DocumentField
        from expenses.views import _build_dynamic_fields_display

        doc_type = M_DocumentType.objects.create(document_type_name='colspanテスト種別B', menu_group=self.grp)
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='x', field_name_view='X', field_type='char',
            field_order=1, row_break=False, section_header='',
        )
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='y', field_name_view='Y', field_type='char',
            field_order=2, row_break=True, section_header='セクションX',
        )
        doc = self._make_document(doc_type, {'x': '1', 'y': '2'})

        rows = _build_dynamic_fields_display(doc)

        section_rows = [r for r in rows if r['type'] == 'section']
        self.assertEqual(len(section_rows), 1)
        self.assertEqual(section_rows[0]['colspan'], 2)
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests.BuildDynamicFieldsDisplaySectionColspanTest -v 2 --keepdb'`

Expected: FAIL（`KeyError: 'colspan'` — `row['colspan']` がまだ存在しないため）

- [ ] **Step 3: 最小限の実装を行う**

`expenses/views.py:289-296` を以下に置き換える:

```python
    # 1フィールドのみの行は td_colspan=3（残3列をスパン）、複数は 1
    for row in rows:
        if row['type'] == 'data':
            n = len(row['fields'])
            for f in row['fields']:
                f['td_colspan'] = 3 if n == 1 else 1

    # セクション見出し行の colspan はテーブルの実列数（最大フィールド数×2）に合わせる。
    # 固定値4だと3項目以上が並ぶデータ行ではテーブル幅と合わず見出しバーが途中で途切れる。
    max_fields = max((len(row['fields']) for row in rows if row['type'] == 'data'), default=2)
    section_colspan = max_fields * 2
    for row in rows:
        if row['type'] == 'section':
            row['colspan'] = section_colspan

    return rows
```

- [ ] **Step 4: テストが成功することを確認する**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests.BuildDynamicFieldsDisplaySectionColspanTest -v 2 --keepdb'`

Expected: PASS（2 tests）

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py expenses/tests.py
git commit -m "fix: 動的フィールドのセクション見出しcolspanをデータ行の実列数に合わせて動的化"
```

---

## Task 2: `is_asset` コンテキストフラグの追加と共有テストフィクスチャ

**Files:**
- Modify: `expenses/views.py:722-739`（`expense_detail` の render context）
- Modify: `expenses/views.py:3445-3461`（`approval_detail` の render context）
- Modify: `expenses/views.py:4104-4118`（`settings_approval_detail` の render context）
- Test: `expenses/tests.py`（共有フィクスチャ Mixin + 3ビューぶんのコンテキストテスト）

**Interfaces:**
- Consumes: `_is_asset_doc_type(doc_type)`（views.py:57-60、既存ヘルパー、変更不要）
- Produces: `AssetDetailFixtureMixin`（`expenses/tests.py` に新規追加するテスト用クラス）。`self.user` / `self.asset_document`（`category='assets'` のDocTypeで作成したT_Document、動的フィールド3つ・明細1件あり） / `self.normal_document`（`category='expense'` のDocTypeで作成したT_Document、動的フィールド1つ・明細1件あり）を提供する。Task 3〜6 はこのMixinを継承して使う。

`expenses/views.py` の3つのビューの `return render(...)` 呼び出しに、それぞれ `"is_asset": _is_asset_doc_type(expense.document_type)` を1行追加する。`_is_asset_doc_type` は既に views.py:57-60 で定義済みで、3つのビュー関数すべてから同じモジュール内なのでimport不要。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/tests.py` の末尾（Task 1で追加したテストクラスの後）に以下を追加する:

```python
class AssetDetailFixtureMixin:
    """固定資産ドキュメントと通常ドキュメントの比較用フィクスチャ。
    expense_detail/approval_detail/settings_approval_detail のテンプレート出し分けテストで共有する。
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from expenses.models import (
            M_DocumentGroup, M_DocumentType, M_DocumentField, M_Status, T_Document, T_DocumentContent,
        )
        User = get_user_model()
        cls.user = User.objects.create_user(
            username='asset_detail_user', man_number='ASTDET1',
            user_name='資産テスト担当', password='pass123',
        )
        cls.status, _ = M_Status.objects.get_or_create(
            status_cd='INPRO', defaults={'status_name': '申請中', 'action_name': '提出'}
        )

        # 固定資産グループ・DocType・動的フィールド3つ・明細1件
        asset_grp, _ = M_DocumentGroup.objects.get_or_create(
            menu_group='ASTDETGRP', defaults={'menu_group_name': '固定資産テストグループ', 'category': 'assets', 'menu_order': 96},
        )
        cls.asset_doc_type = M_DocumentType.objects.create(
            document_type_name='固定資産テスト種別', menu_group=asset_grp,
        )
        M_DocumentField.objects.create(
            document_type=cls.asset_doc_type, field_name='maker_name', field_name_view='製造メーカー名',
            field_type='char', field_order=1, row_break=False,
        )
        M_DocumentField.objects.create(
            document_type=cls.asset_doc_type, field_name='model_no', field_name_view='型式',
            field_type='char', field_order=2, row_break=False,
        )
        M_DocumentField.objects.create(
            document_type=cls.asset_doc_type, field_name='serial_no', field_name_view='製造番号',
            field_type='char', field_order=3, row_break=False,
        )
        cls.asset_document = T_Document.objects.create(
            document_type=cls.asset_doc_type, title='固定資産テスト申請',
            man_number=cls.user, status_cd=cls.status, tsuka_cd='JPY',
        )
        T_DocumentContent.objects.create(
            document=cls.asset_document, purpose='テスト用途A', amount=10000,
            content={'maker_name': 'テストメーカー', 'model_no': 'XYZ-100', 'serial_no': 'SN001'},
        )

        # 通常の経費グループ・DocType・動的フィールド1つ・明細1件（回帰確認用）
        normal_grp, _ = M_DocumentGroup.objects.get_or_create(
            menu_group='PAYDETGRP', defaults={'menu_group_name': '通常テストグループ', 'category': 'expense', 'menu_order': 97},
        )
        cls.normal_doc_type = M_DocumentType.objects.create(
            document_type_name='通常テスト種別', menu_group=normal_grp,
        )
        M_DocumentField.objects.create(
            document_type=cls.normal_doc_type, field_name='note1', field_name_view='備考1',
            field_type='char', field_order=1, row_break=False,
        )
        cls.normal_document = T_Document.objects.create(
            document_type=cls.normal_doc_type, title='通常テスト申請',
            man_number=cls.user, status_cd=cls.status, tsuka_cd='JPY',
        )
        T_DocumentContent.objects.create(
            document=cls.normal_document, purpose='テスト用途B', amount=5000,
            content={'note1': 'メモ'},
        )


class IsAssetContextFlagTest(AssetDetailFixtureMixin, TestCase):
    """expense_detail/approval_detail/settings_approval_detail が is_asset をコンテキストに渡すことを確認する"""

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)

    def test_expense_detail_is_asset_true_for_asset_doctype(self):
        from django.urls import reverse
        url = reverse('expenses:expense_detail', args=[self.asset_document.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_asset'])

    def test_expense_detail_is_asset_false_for_normal_doctype(self):
        from django.urls import reverse
        url = reverse('expenses:expense_detail', args=[self.normal_document.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['is_asset'])

    def test_approval_detail_is_asset_true_for_asset_doctype(self):
        from django.urls import reverse
        url = reverse('expenses:approval_detail', args=[self.asset_document.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_asset'])

    def test_settings_approval_detail_is_asset_true_for_asset_doctype(self):
        from django.urls import reverse
        url = reverse('expenses:settings_approval_detail', args=[self.asset_document.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_asset'])
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests.IsAssetContextFlagTest -v 2 --keepdb'`

Expected: FAIL（`KeyError: 'is_asset'` — まだコンテキストに含まれていないため）

- [ ] **Step 3: 最小限の実装を行う**

`expenses/views.py:722-739` の `expense_detail` の `return render(...)` を以下に変更する（`"is_asset"` の1行を追加）:

```python
    return render(request, "expenses/expense_detail.html", {
        "expense": expense,
        "workflow_actions": workflow_actions,
        "pending_approvers": pending_approvers,
        "currency_name": currency_name,
        "dynamic_fields_display": dynamic_fields_display,
        "progress": progress,
        "is_travel": is_travel,
        "is_asset": _is_asset_doc_type(expense.document_type),
        "travel_route_details": travel_route_details,
        "travel_accom_details": travel_accom_details,
        "travel_allow_details": travel_allow_details,
        "travel_route_subtotal": travel_route_subtotal,
        "back_url": back_url,
        "from_page": from_page,
        "can_keiri_edit": _can_do_keiri_edit(request.user, expense),
        "tax_label_map": _item_label_map('TAX'),
        "coc_label_map": _item_label_map('COC'),
    })
```

`expenses/views.py:3445-3461` の `approval_detail` の `return render(...)` を以下に変更する:

```python
    return render(request, "expenses/approval_detail.html", {
        "expense": expense,
        "form": form,
        "workflow_actions": workflow_actions,
        "pending_approvers": pending_approvers,
        "dynamic_fields_display": dynamic_fields_display,
        "progress": progress,
        "is_travel": is_travel,
        "is_asset": _is_asset_doc_type(expense.document_type),
        "travel_route_details": travel_route_details,
        "travel_accom_details": travel_accom_details,
        "travel_allow_details": travel_allow_details,
        "travel_route_subtotal": travel_route_subtotal,
        "can_keiri_edit": can_keiri_edit,
        "edit_histories": edit_histories,
        "tax_label_map": _item_label_map('TAX'),
        "coc_label_map": _item_label_map('COC'),
    })
```

`expenses/views.py:4104-4118` の `settings_approval_detail` の `return render(...)` を以下に変更する:

```python
    return render(request, 'expenses/settings_approval_detail.html', {
        'expense': expense,
        'workflow_actions': workflow_actions,
        'pending_approvers': pending_approvers,
        'dynamic_fields_display': dynamic_fields_display,
        'progress': progress,
        'return_qs': request.GET.get('return_qs', ''),
        'is_travel': is_travel,
        'is_asset': _is_asset_doc_type(expense.document_type),
        'travel_route_details': travel_route_details,
        'travel_accom_details': travel_accom_details,
        'travel_allow_details': travel_allow_details,
        'travel_route_subtotal': travel_route_subtotal,
        'tax_label_map': _item_label_map('TAX'),
        'coc_label_map': _item_label_map('COC'),
    })
```

- [ ] **Step 4: テストが成功することを確認する**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests.IsAssetContextFlagTest -v 2 --keepdb'`

Expected: PASS（4 tests）

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py expenses/tests.py
git commit -m "feat: expense_detail/approval_detail/settings_approval_detailにis_assetフラグを追加"
```

---

## Task 3: 共有パーシャル `_expense_detail_display.html` の固定資産向け出し分け

**Files:**
- Modify: `expenses/templates/expenses/_expense_detail_display.html:1-111`（全体）
- Test: `expenses/tests.py`（パーシャル単体の `render_to_string` テスト）

**Interfaces:**
- Consumes: `is_asset`（Task 2で導入、呼び出し元テンプレートから継承される `{% include %}` のコンテキスト変数）
- Produces: なし（リーフのテンプレートパーシャル）

このパーシャルは3画面すべてから `{% include "expenses/_expense_detail_display.html" %}`（`only` なし、親コンテキストをそのまま継承）で呼ばれる。`is_asset` が True のとき、カードヘッダーの金額表示を消し、右側情報パネルは「目的」の値のみを表示する（ラベルなし）。

現在の `expenses/templates/expenses/_expense_detail_display.html` の内容は以下の通り（111行）:

```html
{% load expense_extras %}
<div class="card mb-3 expense-detail-item">
    <div class="card-header d-flex justify-content-between align-items-center py-2" style="background:#f9fafb; border-bottom:1px solid #e5e7eb;">
        <span class="fw-semibold small text-muted">明細 {{ forloop.counter }}</span>
        <span class="fw-bold" style="font-size:17px; color:#047857;">
            {{ expense.tsuka_cd|currency_display }} {{ detail.amount|amount_format:expense.tsuka_cd }}
        </span>
    </div>
    <div class="card-body p-0">
        <div class="row g-0">

            {# 左: 添付画像エリア #}
            <div class="col-md-8" style="border-right:1px solid #e5e7eb;">
                {% with atts=detail.attachments.all %}
                {% if atts %}
                    {% for att in atts %}
                    <div {% if not forloop.last %}style="border-bottom:1px solid #e5e7eb;"{% endif %}>
                        {% with fname=att.file.name|lower %}
                        {% if fname|slice:"-4:" == ".pdf" %}
                            {# PDF: サムネイル or アイコン表示、クリックで新しいタブ #}
                            <a href="{{ att.file.url }}" target="_blank" class="receipt-image-link d-block" title="クリックでPDFを新しいタブで表示" style="cursor:pointer; text-align:center;">
                                {% if att.thumbnail %}
                                    <div class="position-relative d-inline-block" style="max-width:400px;">
                                        <img src="{{ att.thumbnail.url }}" alt="PDF" class="receipt-thumbnail" style="max-width:400px;">
                                        <span class="position-absolute bottom-0 end-0 badge bg-danger m-1" style="font-size:10px;"><i class="fas fa-external-link-alt"></i> PDF</span>
                                    </div>
                                {% else %}
                                    <div class="d-flex align-items-center justify-content-center flex-column" style="min-height:80px;">
                                        <i class="fas fa-file-pdf fa-3x text-danger mb-2"></i>
                                        <span class="small text-muted">PDFを表示</span>
                                    </div>
                                {% endif %}
                            </a>
                        {% elif att.thumbnail or fname|slice:"-4:" == ".jpg" or fname|slice:"-5:" == ".jpeg" or fname|slice:"-4:" == ".png" or fname|slice:"-4:" == ".gif" or fname|slice:"-5:" == ".webp" %}
                            {# 画像: 元データを直接表示、クリックでさらにズーム #}
                            <a href="{{ att.file.url }}" class="receipt-image-link d-block lightbox-trigger" title="クリックでさらに拡大" style="cursor:zoom-in;">
                                <img src="{{ att.file.url }}" alt="添付" class="receipt-thumbnail" loading="lazy">
                            </a>
                        {% else %}
                            <div class="receipt-image-link d-flex align-items-center justify-content-center">
                                <a href="{{ att.file.url }}" target="_blank" class="btn btn-lg btn-outline-primary py-4 px-5">
                                    <i class="fas fa-file fa-3x mb-2 d-block"></i>
                                    ファイルを表示
                                </a>
                            </div>
                        {% endif %}
                        {% endwith %}
                    </div>
                    {% endfor %}
                {% else %}
                    <div class="receipt-image-link d-flex align-items-center justify-content-center flex-column">
                        <i class="fas fa-paperclip fa-2x text-muted mb-2"></i>
                        <span class="text-muted small">添付なし</span>
                    </div>
                {% endif %}
                {% endwith %}
            </div>

            {# 右: 全項目リスト #}
            <div class="col-md-4">
                <div class="attachment-info-panel">
                    <div class="info-row">
                        <span class="info-label">取引日</span>
                        <span class="info-value">{{ detail.date|date:"Y/m/d"|default:"-" }}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">金額</span>
                        <span class="info-value info-amount">{{ expense.tsuka_cd|currency_display }} {{ detail.amount|amount_format:expense.tsuka_cd }}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">消費税額</span>
                        <span class="info-value">{% if detail.consumption_tax %}{{ detail.consumption_tax|floatformat:0 }} 円{% else %}-{% endif %}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">内外税区分</span>
                        <span class="info-value">{% if detail.consumption_kbn is not None %}{% with k=detail.consumption_kbn|stringformat:"s" %}{{ tax_label_map|get_item:k|default:k }}{% endwith %}{% else %}-{% endif %}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">目的</span>
                        <span class="info-value">{{ detail.purpose|default:"-" }}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">支払先</span>
                        <span class="info-value">{{ detail.shiharaisaki|default:"-" }}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">勘定科目</span>
                        <span class="info-value">{{ detail.account.account_name|default:"-" }}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">登録番号</span>
                        <span class="info-value">{{ detail.tekikaku_cd|default:"-" }}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">コーポレートカード</span>
                        <span class="info-value">
                            {% if detail.corpo_card is not None %}
                                {% with k=detail.corpo_card|stringformat:"s" %}
                                {{ coc_label_map|get_item:k|default:k }}
                                {% endwith %}
                                {% if detail.corpo_card_no %}&nbsp;{{ detail.corpo_card_no }}{% endif %}
                            {% else %}-{% endif %}
                        </span>
                    </div>
                </div>
            </div>

        </div>
    </div>
</div>
```

- [ ] **Step 1: 失敗するテストを書く**

`expenses/tests.py` の末尾に以下を追加する:

```python
class ExpenseDetailDisplayPartialAssetTest(AssetDetailFixtureMixin, TestCase):
    """_expense_detail_display.html の is_asset 出し分けを単体でテストする"""

    def test_partial_shows_only_purpose_value_for_asset(self):
        from django.template.loader import render_to_string
        detail = self.asset_document.contents.first()
        html = render_to_string('expenses/_expense_detail_display.html', {
            'expense': self.asset_document,
            'detail': detail,
            'is_asset': True,
            'tax_label_map': {},
            'coc_label_map': {},
        })
        self.assertNotIn('目的', html)
        self.assertNotIn('取引日', html)
        self.assertNotIn('支払先', html)
        self.assertNotIn('info-label', html)
        self.assertNotIn('font-size:17px', html)
        self.assertIn('テスト用途A', html)

    def test_partial_shows_full_panel_for_non_asset(self):
        from django.template.loader import render_to_string
        detail = self.normal_document.contents.first()
        html = render_to_string('expenses/_expense_detail_display.html', {
            'expense': self.normal_document,
            'detail': detail,
            'is_asset': False,
            'tax_label_map': {},
            'coc_label_map': {},
        })
        self.assertIn('目的', html)
        self.assertIn('取引日', html)
        self.assertIn('font-size:17px', html)
        self.assertIn('テスト用途B', html)
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests.ExpenseDetailDisplayPartialAssetTest -v 2 --keepdb'`

Expected: FAIL（`test_partial_shows_only_purpose_value_for_asset` が失敗 — まだ `is_asset` の出し分けがなく全項目が表示されるため `assertNotIn('目的', html)` 等が失敗する）

- [ ] **Step 3: 最小限の実装を行う**

`expenses/templates/expenses/_expense_detail_display.html` の3-8行目（カードヘッダー）を以下に置き換える:

```html
    <div class="card-header d-flex justify-content-between align-items-center py-2" style="background:#f9fafb; border-bottom:1px solid #e5e7eb;">
        <span class="fw-semibold small text-muted">明細 {{ forloop.counter }}</span>
        {% if not is_asset %}
        <span class="fw-bold" style="font-size:17px; color:#047857;">
            {{ expense.tsuka_cd|currency_display }} {{ detail.amount|amount_format:expense.tsuka_cd }}
        </span>
        {% endif %}
    </div>
```

同ファイルの60-106行目（右側情報パネル全体）を以下に置き換える:

```html
            <div class="col-md-4">
                <div class="attachment-info-panel">
                    {% if is_asset %}
                    <div class="info-row">
                        <span class="info-value">{{ detail.purpose|default:"-" }}</span>
                    </div>
                    {% else %}
                    <div class="info-row">
                        <span class="info-label">取引日</span>
                        <span class="info-value">{{ detail.date|date:"Y/m/d"|default:"-" }}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">金額</span>
                        <span class="info-value info-amount">{{ expense.tsuka_cd|currency_display }} {{ detail.amount|amount_format:expense.tsuka_cd }}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">消費税額</span>
                        <span class="info-value">{% if detail.consumption_tax %}{{ detail.consumption_tax|floatformat:0 }} 円{% else %}-{% endif %}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">内外税区分</span>
                        <span class="info-value">{% if detail.consumption_kbn is not None %}{% with k=detail.consumption_kbn|stringformat:"s" %}{{ tax_label_map|get_item:k|default:k }}{% endwith %}{% else %}-{% endif %}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">目的</span>
                        <span class="info-value">{{ detail.purpose|default:"-" }}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">支払先</span>
                        <span class="info-value">{{ detail.shiharaisaki|default:"-" }}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">勘定科目</span>
                        <span class="info-value">{{ detail.account.account_name|default:"-" }}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">登録番号</span>
                        <span class="info-value">{{ detail.tekikaku_cd|default:"-" }}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">コーポレートカード</span>
                        <span class="info-value">
                            {% if detail.corpo_card is not None %}
                                {% with k=detail.corpo_card|stringformat:"s" %}
                                {{ coc_label_map|get_item:k|default:k }}
                                {% endwith %}
                                {% if detail.corpo_card_no %}&nbsp;{{ detail.corpo_card_no }}{% endif %}
                            {% else %}-{% endif %}
                        </span>
                    </div>
                    {% endif %}
                </div>
            </div>
```

- [ ] **Step 4: テストが成功することを確認する**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests.ExpenseDetailDisplayPartialAssetTest -v 2 --keepdb'`

Expected: PASS（2 tests）

- [ ] **Step 5: コミット**

```bash
git add expenses/templates/expenses/_expense_detail_display.html expenses/tests.py
git commit -m "feat: 明細カードのis_asset出し分け（金額非表示・目的のみ表示）を_expense_detail_display.htmlに実装"
```

---

## Task 4: `expense_detail.html` の固定資産レイアウト適用

**Files:**
- Modify: `expenses/templates/expenses/expense_detail.html:50-65,73,81,178,185-188`
- Test: `expenses/tests.py`（`Client.get` によるレンダリング確認テスト）

**Interfaces:**
- Consumes: `is_asset`（Task 2）、`row.colspan`（Task 1）、Task 3 で更新済みの `_expense_detail_display.html`
- Produces: なし（リーフのページテンプレート）

- [ ] **Step 1: 失敗するテストを書く**

`expenses/tests.py` の末尾に以下を追加する:

```python
class ExpenseDetailAssetLayoutTest(AssetDetailFixtureMixin, TestCase):
    """expense_detail.html の固定資産レイアウト出し分けを確認する"""

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)

    def test_asset_document_hides_currency_and_total_and_renames_headings(self):
        from django.urls import reverse
        url = reverse('expenses:expense_detail', args=[self.asset_document.pk])
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<th>通貨</th>', content)
        self.assertNotIn('合計金額', content)
        self.assertIn('固定資産情報', content)
        self.assertIn('資産画像', content)
        self.assertNotIn('>経費明細<', content)

    def test_normal_document_keeps_existing_layout(self):
        from django.urls import reverse
        url = reverse('expenses:expense_detail', args=[self.normal_document.pk])
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertIn('<th>通貨</th>', content)
        self.assertIn('合計金額', content)
        self.assertIn('追加入力項目', content)
        self.assertIn('>経費明細<', content)
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests.ExpenseDetailAssetLayoutTest -v 2 --keepdb'`

Expected: FAIL（`test_asset_document_hides_currency_and_total_and_renames_headings` が失敗 — まだ `is_asset` 出し分けがテンプレートに実装されていないため）

- [ ] **Step 3: 最小限の実装を行う**

`expenses/templates/expenses/expense_detail.html:50-65`（申請情報テーブル）を以下に置き換える:

```html
                    <table class="info-table">
                        <tbody>
                            <tr><th>申請者</th><td colspan="3">{{ expense.applicant.user_name }}</td></tr>
                            <tr><th>申請日時</th><td colspan="3">{{ expense.created_at|date:"Y年m月d日 H:i" }}</td></tr>
                            <tr><th>負担部門</th><td colspan="3">{{ expense.bumon_cd.bumon_name|default:"-" }}</td></tr>
                            {% if not is_asset %}<tr><th>通貨</th><td colspan="3">{% if expense.tsuka_cd %}{{ expense.tsuka_cd }}{% if currency_name %}（{{ currency_name }}）{% endif %}{% else %}-{% endif %}</td></tr>{% endif %}
                            <tr><th>備考</th><td colspan="3">{{ expense.memo|default:"-" }}</td></tr>
                            {% if expense.ringi_no %}<tr><th>稟議No</th><td colspan="3">{{ expense.ringi_no }}</td></tr>{% endif %}
                            {% if is_asset %}
                            <tr><th>ステータス</th><td colspan="3"><span class="{{ expense.status_cd.status_cd|status_badge_class }}">{% status_label expense progress %}</span></td></tr>
                            {% else %}
                            <tr>
                                <th>ステータス</th>
                                <td><span class="{{ expense.status_cd.status_cd|status_badge_class }}">{% status_label expense progress %}</span></td>
                                <th>合計金額</th>
                                <td class="fw-bold text-success fs-5">{{ expense.tsuka_cd|currency_display }} {{ expense.total_amount|amount_format:expense.tsuka_cd }}</td>
                            </tr>
                            {% endif %}
                        </tbody>
                    </table>
```

73行目（動的フィールドの見出し）を以下に置き換える:

```html
                    <h5 class="mb-0" style="color:#fff !important;"><i class="fas fa-list me-2" style="color:#fff !important;"></i>{% if first_row.type == 'section' %}{{ first_row.header }}{% elif is_asset %}固定資産情報{% else %}追加入力項目{% endif %}</h5>
```

81行目（セクション見出し行の colspan）を以下に置き換える:

```html
                            <tr class="info-table-section"><th colspan="{{ row.colspan }}">{{ row.header }}</th></tr>
```

178行目（経費明細カードの見出し）を以下に置き換える:

```html
                    <h5 class="card-title mb-0" style="color:#fff !important;"><i class="fas fa-list me-2" style="color:#fff !important;"></i>{% if is_asset %}資産画像{% else %}経費明細{% endif %}</h5>
```

185-188行目（合計金額バー）を以下に置き換える:

```html
                        {% if not is_asset %}
                        <div class="detail-total-bar mt-3">
                            <span class="fw-normal" style="color:#047857; font-size:14px;">合計金額</span>
                            {{ expense.tsuka_cd|currency_display }} {{ expense.total_amount|amount_format:expense.tsuka_cd }}
                        </div>
                        {% endif %}
```

- [ ] **Step 4: テストが成功することを確認する**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests.ExpenseDetailAssetLayoutTest -v 2 --keepdb'`

Expected: PASS（2 tests）

- [ ] **Step 5: コミット**

```bash
git add expenses/templates/expenses/expense_detail.html expenses/tests.py
git commit -m "feat: expense_detail.htmlに固定資産レイアウト（通貨/合計金額非表示・見出し変更）を適用"
```

---

## Task 5: `approval_detail.html` の固定資産レイアウト適用

**Files:**
- Modify: `expenses/templates/expenses/approval_detail.html:196-208,218,226,323,330-333`
- Test: `expenses/tests.py`（`Client.get` によるレンダリング確認テスト）

**Interfaces:**
- Consumes: `is_asset`（Task 2）、`row.colspan`（Task 1）、Task 3 で更新済みの `_expense_detail_display.html`
- Produces: なし（リーフのページテンプレート）

`approval_detail.html` は `expense_detail.html` と同じ構造を持つ別テンプレート（承認画面用）。Task 4 と同じ変更パターンを、このファイルの対応箇所に適用する。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/tests.py` の末尾に以下を追加する:

```python
class ApprovalDetailAssetLayoutTest(AssetDetailFixtureMixin, TestCase):
    """approval_detail.html の固定資産レイアウト出し分けを確認する"""

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)

    def test_asset_document_hides_currency_and_total_and_renames_headings(self):
        from django.urls import reverse
        url = reverse('expenses:approval_detail', args=[self.asset_document.pk])
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<th>通貨</th>', content)
        self.assertNotIn('合計金額', content)
        self.assertIn('固定資産情報', content)
        self.assertIn('資産画像', content)
        self.assertNotIn('>経費明細<', content)

    def test_normal_document_keeps_existing_layout(self):
        from django.urls import reverse
        url = reverse('expenses:approval_detail', args=[self.normal_document.pk])
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertIn('<th>通貨</th>', content)
        self.assertIn('合計金額', content)
        self.assertIn('追加入力項目', content)
        self.assertIn('>経費明細<', content)
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests.ApprovalDetailAssetLayoutTest -v 2 --keepdb'`

Expected: FAIL（`test_asset_document_hides_currency_and_total_and_renames_headings` が失敗）

- [ ] **Step 3: 最小限の実装を行う**

`expenses/templates/expenses/approval_detail.html:196-208`（申請情報テーブル）を以下に置き換える:

```html
                        <tbody>
                            <tr><th>申請者</th><td colspan="3">{{ expense.applicant.user_name }}</td></tr>
                            <tr><th>申請日時</th><td colspan="3">{{ expense.created_at|date:"Y年m月d日 H:i" }}</td></tr>
                            <tr><th>負担部門</th><td colspan="3">{{ expense.bumon_cd.bumon_name|default:"-" }}</td></tr>
                            {% if not is_asset %}<tr><th>通貨</th><td colspan="3">{% if expense.tsuka_cd %}{{ expense.tsuka_cd }}{% else %}-{% endif %}</td></tr>{% endif %}
                            {% if expense.memo %}<tr><th>備考</th><td colspan="3">{{ expense.memo }}</td></tr>{% endif %}
                            {% if expense.ringi_no %}<tr><th>稟議No</th><td colspan="3">{{ expense.ringi_no }}</td></tr>{% endif %}
                            {% if is_asset %}
                            <tr><th>ステータス</th><td colspan="3"><span class="badge badge-inprogress"><i class="fas fa-clock me-1"></i>{% status_label expense progress %}</span></td></tr>
                            {% else %}
                            <tr>
                                <th>ステータス</th>
                                <td><span class="badge badge-inprogress"><i class="fas fa-clock me-1"></i>{% status_label expense progress %}</span></td>
                                <th>合計金額</th>
                                <td class="fw-bold text-success fs-5">{{ expense.tsuka_cd|currency_display }} {{ expense.total_amount|amount_format:expense.tsuka_cd }}</td>
                            </tr>
                            {% endif %}
                        </tbody>
```

218行目（動的フィールドの見出し）を以下に置き換える:

```html
                            <h5 class="mb-0" style="color:#fff !important;"><i class="fas fa-list me-2" style="color:#fff !important;"></i>{% if first_row.type == 'section' %}{{ first_row.header }}{% elif is_asset %}固定資産情報{% else %}追加入力項目{% endif %}</h5>
```

226行目（セクション見出し行の colspan）を以下に置き換える:

```html
                                    <tr class="info-table-section"><th colspan="{{ row.colspan }}">{{ row.header }}</th></tr>
```

323行目（経費明細カードの見出し）を以下に置き換える:

```html
                            <h5 class="mb-0" style="color:#fff !important;"><i class="fas fa-list me-2" style="color:#fff !important;"></i>{% if is_asset %}資産画像{% else %}経費明細{% endif %}</h5>
```

330-333行目（合計金額バー）を以下に置き換える:

```html
                                {% if not is_asset %}
                                <div class="detail-total-bar mt-3">
                                    <span class="fw-normal" style="color:#047857; font-size:14px;">合計金額</span>
                                    {{ expense.tsuka_cd|currency_display }} {{ expense.total_amount|amount_format:expense.tsuka_cd }}
                                </div>
                                {% endif %}
```

- [ ] **Step 4: テストが成功することを確認する**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests.ApprovalDetailAssetLayoutTest -v 2 --keepdb'`

Expected: PASS（2 tests）

- [ ] **Step 5: コミット**

```bash
git add expenses/templates/expenses/approval_detail.html expenses/tests.py
git commit -m "feat: approval_detail.htmlに固定資産レイアウト（通貨/合計金額非表示・見出し変更）を適用"
```

---

## Task 6: `settings_approval_detail.html` の固定資産レイアウト適用

**Files:**
- Modify: `expenses/templates/expenses/settings_approval_detail.html:85-104,117,125,222,229-232`
- Test: `expenses/tests.py`（`Client.get` によるレンダリング確認テスト）

**Interfaces:**
- Consumes: `is_asset`（Task 2）、`row.colspan`（Task 1）、Task 3 で更新済みの `_expense_detail_display.html`
- Produces: なし（リーフのページテンプレート）

`settings_approval_detail.html` は管理者用「承認管理」詳細画面で、`approval_detail.html` と同じ構造を持つ。Task 4/5 と同じ変更パターンを、このファイルの対応箇所に適用する。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/tests.py` の末尾に以下を追加する:

```python
class SettingsApprovalDetailAssetLayoutTest(AssetDetailFixtureMixin, TestCase):
    """settings_approval_detail.html の固定資産レイアウト出し分けを確認する"""

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)

    def test_asset_document_hides_currency_and_total_and_renames_headings(self):
        from django.urls import reverse
        url = reverse('expenses:settings_approval_detail', args=[self.asset_document.pk])
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<th>通貨</th>', content)
        self.assertNotIn('合計金額', content)
        self.assertIn('固定資産情報', content)
        self.assertIn('資産画像', content)
        self.assertNotIn('>経費明細<', content)

    def test_normal_document_keeps_existing_layout(self):
        from django.urls import reverse
        url = reverse('expenses:settings_approval_detail', args=[self.normal_document.pk])
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertIn('<th>通貨</th>', content)
        self.assertIn('合計金額', content)
        self.assertIn('追加入力項目', content)
        self.assertIn('>経費明細<', content)
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests.SettingsApprovalDetailAssetLayoutTest -v 2 --keepdb'`

Expected: FAIL（`test_asset_document_hides_currency_and_total_and_renames_headings` が失敗）

- [ ] **Step 3: 最小限の実装を行う**

`expenses/templates/expenses/settings_approval_detail.html:85-104`（申請情報テーブル）を以下に置き換える（既存の `{% if expense.status_cd.status_cd == 'FNS' %}...{% endif %}` のステータスバッジ分岐は変更しない）:

```html
                        <tbody>
                            <tr><th>申請者</th><td colspan="3">{{ expense.applicant.user_name }}</td></tr>
                            <tr><th>申請日時</th><td colspan="3">{{ expense.created_at|date:"Y年m月d日 H:i" }}</td></tr>
                            <tr><th>負担部門</th><td colspan="3">{{ expense.bumon_cd.bumon_name|default:"-" }}</td></tr>
                            {% if not is_asset %}<tr><th>通貨</th><td colspan="3">{% if expense.tsuka_cd %}{{ expense.tsuka_cd }}{% else %}-{% endif %}</td></tr>{% endif %}
                            {% if expense.memo %}<tr><th>備考</th><td colspan="3">{{ expense.memo }}</td></tr>{% endif %}
                            {% if expense.ringi_no %}<tr><th>稟議No</th><td colspan="3">{{ expense.ringi_no }}</td></tr>{% endif %}
                            <tr>
                                <th>ステータス</th>
                                <td{% if is_asset %} colspan="3"{% endif %}>
                                    {% if expense.status_cd.status_cd == 'FNS' %}
                                        <span class="badge bg-success">{% status_label expense progress %}</span>
                                    {% elif expense.status_cd.status_cd == 'REJECTED' %}
                                        <span class="badge bg-danger">{% status_label expense progress %}</span>
                                    {% elif expense.status_cd.status_cd == 'DRAFT' %}
                                        <span class="badge bg-secondary">{% status_label expense progress %}</span>
                                    {% else %}
                                        <span class="badge badge-inprogress"><i class="fas fa-clock me-1"></i>{% status_label expense progress %}</span>
                                    {% endif %}
                                </td>
                                {% if not is_asset %}
                                <th>合計金額</th>
                                <td class="fw-bold text-success fs-5">{{ expense.tsuka_cd|currency_display }} {{ expense.total_amount|amount_format:expense.tsuka_cd }}</td>
                                {% endif %}
                            </tr>
                        </tbody>
```

117行目（動的フィールドの見出し）を以下に置き換える:

```html
                    <h5 class="mb-0" style="color:#fff !important;"><i class="fas fa-list me-2" style="color:#fff !important;"></i>{% if first_row.type == 'section' %}{{ first_row.header }}{% elif is_asset %}固定資産情報{% else %}追加入力項目{% endif %}</h5>
```

125行目（セクション見出し行の colspan）を以下に置き換える:

```html
                            <tr class="info-table-section"><th colspan="{{ row.colspan }}">{{ row.header }}</th></tr>
```

222行目（経費明細カードの見出し）を以下に置き換える:

```html
                    <h5 class="mb-0" style="color:#fff !important;"><i class="fas fa-list me-2" style="color:#fff !important;"></i>{% if is_asset %}資産画像{% else %}経費明細{% endif %}</h5>
```

229-232行目（合計金額バー）を以下に置き換える:

```html
                        {% if not is_asset %}
                        <div class="detail-total-bar mt-3">
                            <span class="fw-normal" style="color:#047857; font-size:14px;">合計金額</span>
                            {{ expense.tsuka_cd|currency_display }} {{ expense.total_amount|amount_format:expense.tsuka_cd }}
                        </div>
                        {% endif %}
```

- [ ] **Step 4: テストが成功することを確認する**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests.SettingsApprovalDetailAssetLayoutTest -v 2 --keepdb'`

Expected: PASS（2 tests）

- [ ] **Step 5: コミット**

```bash
git add expenses/templates/expenses/settings_approval_detail.html expenses/tests.py
git commit -m "feat: settings_approval_detail.htmlに固定資産レイアウト（通貨/合計金額非表示・見出し変更）を適用"
```

---

## 最終確認

全タスク完了後、以下を実行してリグレッションがないことを確認する:

```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /home/idc_user/expense_project2 && source .venv/bin/activate && python manage.py test expenses.tests -v 2 --keepdb'
```

Expected: 全テスト PASS（既存テスト + 本Planで追加したテスト）。`expenses/test_travel_expense.py` の既存・無関係の8件失敗は対象外（環境差異によるベースライン既知事象）。

実装完了後、開発サーバーで固定資産取得報告書（DocType=6）の実際の申請詳細・承認画面・承認管理画面を目視確認し、レイアウト崩れがないことを確認する。
