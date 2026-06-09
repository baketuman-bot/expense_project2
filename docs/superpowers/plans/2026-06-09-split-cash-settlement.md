# 現金精算処理の本社・大阪分割 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 精算処理メニューの「現金精算処理」を「本社現金精算処理（pay_kbn='03'）」と「大阪現金精算処理（pay_kbn='02'）」の2つに分割する。

**Architecture:** `_settlement_payment_view` に `pay_kbn` フィルタパラメータを追加し、本社・大阪それぞれ専用のビュー関数を設ける。既存の `settle_kbn='CAS_PRE'` / `'CAS_INPRO'` は変更せず、クエリ時に `document__pay_kbn` で絞り込む。

**Tech Stack:** Django 5.x, Python 3.12, MySQL

---

## ファイル変更一覧

| ファイル | 変更内容 |
|---|---|
| `expenses/views.py` | `_settlement_payment_view` に `pay_kbn` 引数追加、`settlement_cash` 廃止、`settlement_cash_hq` / `settlement_cash_osaka` 追加、`settlement_menu` counts更新、`back_url_map` 更新、`settlement_cash_print` リダイレクト先更新 |
| `expenses/urls.py` | `settlement_cash` 削除、`settlement_cash_hq` / `settlement_cash_osaka` 追加 |
| `expenses/templates/expenses/settlement_menu.html` | 現金精算1カードを2カードに分割 |

---

## Task 1: `_settlement_payment_view` に `pay_kbn` フィルタ引数を追加

**Files:**
- Modify: `expenses/views.py` の `_settlement_payment_view` 関数（約4669行付近）

- [ ] **Step 1: 現状確認**

`expenses/views.py` の `_settlement_payment_view` の現在のシグネチャを確認する：

```
def _settlement_payment_view(request, pre_kbn, inpro_kbn, page_title, icon,
                              current_name, process_label, from_param):
```

- [ ] **Step 2: `pay_kbn` 引数を追加してフィルタを適用**

`_settlement_payment_view` のシグネチャと、`contents` クエリ部分を以下に変更する：

```python
def _settlement_payment_view(request, pre_kbn, inpro_kbn, page_title, icon,
                              current_name, process_label, from_param, pay_kbn=None):
    """精算処理共通ビュー: pre_kbn → inpro_kbn への確定処理を共通化"""
```

`contents` の取得箇所（約4723行付近）を変更：

```python
    contents = (
        T_DocumentContent.objects
        .select_related('document', 'document__document_type')
        .filter(settle_kbn=pre_kbn, document__status_cd_id='FNS')
        .order_by('document__document_type_id', 'document__document_id', 'date')
    )
    if pay_kbn:
        contents = contents.filter(document__pay_kbn=pay_kbn)
```

- [ ] **Step 3: 動作確認（手動）**

開発サーバーを起動し、`/settings/settlement/cash/` にアクセスして既存の現金精算処理が引き続き正常動作することを確認する（`pay_kbn=None` の場合はフィルタなし = 従来通り）。

---

## Task 2: `settlement_cash_hq` / `settlement_cash_osaka` ビューを追加、`settlement_cash` を廃止

**Files:**
- Modify: `expenses/views.py`（約4744行付近）

- [ ] **Step 1: `settlement_cash` ビューを2つに置き換える**

既存の `settlement_cash` ビュー：

```python
@login_required
def settlement_cash(request):
    """現金精算処理"""
    return _settlement_payment_view(
        request,
        pre_kbn='CAS_PRE', inpro_kbn='CAS_INPRO',
        page_title='現金精算処理', icon='fa-money-bill-wave',
        current_name='settlement_cash', process_label='現金精算',
        from_param='settlement_cash',
    )
```

を以下2つに置き換える（`settlement_cash` 関数を削除し、以下を追加）：

```python
@login_required
def settlement_cash_hq(request):
    """本社現金精算処理 (pay_kbn='03')"""
    return _settlement_payment_view(
        request,
        pre_kbn='CAS_PRE', inpro_kbn='CAS_INPRO',
        page_title='本社現金精算処理', icon='fa-money-bill-wave',
        current_name='settlement_cash_hq', process_label='現金精算(本社)',
        from_param='settlement_cash_hq', pay_kbn='03',
    )


@login_required
def settlement_cash_osaka(request):
    """大阪現金精算処理 (pay_kbn='02')"""
    return _settlement_payment_view(
        request,
        pre_kbn='CAS_PRE', inpro_kbn='CAS_INPRO',
        page_title='大阪現金精算処理', icon='fa-money-bill-wave',
        current_name='settlement_cash_osaka', process_label='現金精算(大阪)',
        from_param='settlement_cash_osaka', pay_kbn='02',
    )
```

---

## Task 3: `settlement_menu` の `counts` を本社・大阪に分割

**Files:**
- Modify: `expenses/views.py` の `settlement_menu` ビュー（約4589行付近）

- [ ] **Step 1: `counts` の `cash` キーを `cash_hq` / `cash_osaka` に変更**

現在：

```python
    counts = {
        'classify':   base_qs.filter(settle_kbn__isnull=True).count(),
        'cash':       base_qs.filter(settle_kbn='CAS_PRE').count(),
        'transfer':   base_qs.filter(settle_kbn='LON_PRE').count(),
        'corp_card':  base_qs.filter(settle_kbn='COC_PRE').count(),
        'payroll':    base_qs.filter(settle_kbn='SAL_PRE').count(),
        'auto_debit': base_qs.filter(settle_kbn='AUT_PRE').count(),
        'journal':    base_qs.filter(settle_kbn__in=journal_kbns).count(),
    }
```

変更後：

```python
    counts = {
        'classify':    base_qs.filter(settle_kbn__isnull=True).count(),
        'cash_hq':     base_qs.filter(settle_kbn='CAS_PRE', document__pay_kbn='03').count(),
        'cash_osaka':  base_qs.filter(settle_kbn='CAS_PRE', document__pay_kbn='02').count(),
        'transfer':    base_qs.filter(settle_kbn='LON_PRE').count(),
        'corp_card':   base_qs.filter(settle_kbn='COC_PRE').count(),
        'payroll':     base_qs.filter(settle_kbn='SAL_PRE').count(),
        'auto_debit':  base_qs.filter(settle_kbn='AUT_PRE').count(),
        'journal':     base_qs.filter(settle_kbn__in=journal_kbns).count(),
    }
```

---

## Task 4: `back_url_map` と `settlement_cash_print` のリダイレクト先を更新

**Files:**
- Modify: `expenses/views.py` の `expense_detail` ビュー（約664行付近）と `settlement_cash_print`（約4769行付近）

- [ ] **Step 1: `back_url_map` に本社・大阪のURLを追加し `settlement_cash` エントリを削除**

現在（約666〜672行）：

```python
    back_url_map = {
        'settlement':             reverse('expenses:settlement_list'),
        'settlement_classify':    reverse('expenses:settlement_classify'),
        'settlement_cash':        reverse('expenses:settlement_cash'),
        'settlement_corp_card':   reverse('expenses:settlement_corp_card'),
        'settlement_payroll':     reverse('expenses:settlement_payroll'),
    }
```

変更後：

```python
    back_url_map = {
        'settlement':              reverse('expenses:settlement_list'),
        'settlement_classify':     reverse('expenses:settlement_classify'),
        'settlement_cash_hq':      reverse('expenses:settlement_cash_hq'),
        'settlement_cash_osaka':   reverse('expenses:settlement_cash_osaka'),
        'settlement_corp_card':    reverse('expenses:settlement_corp_card'),
        'settlement_payroll':      reverse('expenses:settlement_payroll'),
    }
```

- [ ] **Step 2: `settlement_cash_print` の `redirect` 先を `settlement_menu` に変更**

`settlement_cash_print` ビュー内（約4769行付近）：

現在：
```python
    if not selected_ids:
        return redirect('expenses:settlement_cash')
```

変更後：
```python
    if not selected_ids:
        return redirect('expenses:settlement_menu')
```

---

## Task 5: `urls.py` の URL定義を更新

**Files:**
- Modify: `expenses/urls.py`（約56行付近）

- [ ] **Step 1: `settlement_cash` を廃止し2つのURLを追加**

現在：

```python
    path("settings/settlement/cash/", views.settlement_cash, name="settlement_cash"),
    path("settings/settlement/cash/print/", views.settlement_cash_print, name="settlement_cash_print"),
```

変更後：

```python
    path("settings/settlement/cash/hq/", views.settlement_cash_hq, name="settlement_cash_hq"),
    path("settings/settlement/cash/osaka/", views.settlement_cash_osaka, name="settlement_cash_osaka"),
    path("settings/settlement/cash/print/", views.settlement_cash_print, name="settlement_cash_print"),
```

---

## Task 6: `settlement_menu.html` のカードを2つに分割

**Files:**
- Modify: `expenses/templates/expenses/settlement_menu.html`

- [ ] **Step 1: 現金精算の1カードを本社・大阪の2カードに置き換える**

現在の現金精算カード（約32〜47行）：

```html
    <div class="col-md-4">
      <a href="{% url 'expenses:settlement_cash' %}" class="text-decoration-none">
        <div class="card h-100 card-hover-primary">
          <div class="card-body d-flex align-items-center gap-3 py-4">
            <span class="pt-ico flex-shrink-0"><i class="fas fa-money-bill-wave"></i></span>
            <div class="flex-grow-1">
              <div class="fw-bold">現金精算処理</div>
              <div class="text-muted small">現金で精算する申請を処理</div>
            </div>
            {% if counts.cash %}
            <span class="badge rounded-pill fs-6 px-3 py-2" style="background:#dc3545; color:#fff;">{{ counts.cash }}</span>
            {% endif %}
          </div>
        </div>
      </a>
    </div>
```

変更後（2カードに置き換え）：

```html
    <div class="col-md-4">
      <a href="{% url 'expenses:settlement_cash_hq' %}" class="text-decoration-none">
        <div class="card h-100 card-hover-primary">
          <div class="card-body d-flex align-items-center gap-3 py-4">
            <span class="pt-ico flex-shrink-0"><i class="fas fa-money-bill-wave"></i></span>
            <div class="flex-grow-1">
              <div class="fw-bold">本社現金精算処理</div>
              <div class="text-muted small">本社現金で精算する申請を処理</div>
            </div>
            {% if counts.cash_hq %}
            <span class="badge rounded-pill fs-6 px-3 py-2" style="background:#dc3545; color:#fff;">{{ counts.cash_hq }}</span>
            {% endif %}
          </div>
        </div>
      </a>
    </div>

    <div class="col-md-4">
      <a href="{% url 'expenses:settlement_cash_osaka' %}" class="text-decoration-none">
        <div class="card h-100 card-hover-primary">
          <div class="card-body d-flex align-items-center gap-3 py-4">
            <span class="pt-ico flex-shrink-0"><i class="fas fa-money-bill-wave"></i></span>
            <div class="flex-grow-1">
              <div class="fw-bold">大阪現金精算処理</div>
              <div class="text-muted small">大阪現金で精算する申請を処理</div>
            </div>
            {% if counts.cash_osaka %}
            <span class="badge rounded-pill fs-6 px-3 py-2" style="background:#dc3545; color:#fff;">{{ counts.cash_osaka }}</span>
            {% endif %}
          </div>
        </div>
      </a>
    </div>
```

---

## Task 7: 動作確認とコミット

- [ ] **Step 1: 開発サーバーを起動して動作確認**

```bash
python3 manage.py runserver
```

確認項目：
1. `/settings/settlement/` メニューに「本社現金精算処理」と「大阪現金精算処理」の2カードが表示される
2. 各カードのバッジ件数が正しい（pay_kbn='03' / '02' で絞り込まれている）
3. 「本社現金精算処理」をクリックすると `/settings/settlement/cash/hq/` に遷移し、pay_kbn='03' の明細だけ表示される
4. 「大阪現金精算処理」をクリックすると `/settings/settlement/cash/osaka/` に遷移し、pay_kbn='02' の明細だけ表示される
5. 精算詳細画面で「一覧に戻る」が正しい精算処理画面に戻る
6. `/settings/settlement/cash/` にアクセスすると 404 になる（URL廃止確認）

- [ ] **Step 2: コミット**

```bash
git add expenses/views.py expenses/urls.py expenses/templates/expenses/settlement_menu.html
git commit -m "feat: 現金精算処理を本社・大阪の2メニューに分割

pay_kbn='03'(本社)と'02'(大阪)で絞り込む2ビューを追加。
settlement_cash を廃止し settlement_cash_hq / settlement_cash_osaka に置き換え。"
```
