# フロントエンド UX 改善 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 申請者・承認者両ロールの操作体験を改善する8項目のフロントエンドUX改善を実装する

**Architecture:** 新規JS関数は `base.html` のグローバルJSブロックに集約して各テンプレートから呼び出す。新規CSSは `swiss.css` 末尾に追記。テンプレートは最小限の変更。Django側（views.py/forms.py）は変更なし。

**Tech Stack:** Django Templates, Bootstrap 5.3, Font Awesome 5, vanilla JavaScript

---

## 変更ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `expenses/static/expenses/swiss.css` | `.empty-state`, `.precision-breadcrumb`, ページネーションpadding拡大 |
| `expenses/templates/expenses/base.html` | `bindFormSubmitLock`, `bindFormDirtyGuard`, `initFieldValidation` JS追加 |
| `expenses/templates/expenses/expense_form.html` | 二重送信防止・エラースクロール・beforeunload・blur バリデーション |
| `expenses/templates/expenses/travel_expense_form.html` | 同上 |
| `expenses/templates/expenses/approval_detail.html` | 承認確認 Bootstrap モーダル |
| `expenses/templates/expenses/expense_list.html` | 空状態統一・ページネーション改善 |
| `expenses/templates/expenses/approval_list.html` | 空状態統一・ページネーション改善 |
| `expenses/templates/expenses/home.html` | 空状態統一 |
| `expenses/templates/expenses/expense_detail.html` | ブレッドクラム追加 |
| `expenses/templates/expenses/expense_edit.html` | ブレッドクラム追加 |

---

## Task 1: swiss.css に Empty State・Breadcrumb・Pagination CSS を追加

**Files:**
- Modify: `expenses/static/expenses/swiss.css`（末尾に追記）

- [ ] **Step 1: swiss.css の末尾に以下を追記する**

```css
/* ===== Empty State ===== */
.empty-state {
  text-align: center;
  padding: 56px 24px;
  color: var(--sub);
}
.empty-state-icon {
  font-size: 40px;
  color: var(--muted);
  margin-bottom: 16px;
}
.empty-state-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 6px;
}
.empty-state-desc {
  font-size: 13px;
  color: var(--sub);
  margin-bottom: 20px;
}

/* ===== Breadcrumb ===== */
.precision-breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--sub);
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.precision-breadcrumb a {
  color: var(--primary);
  text-decoration: none;
}
.precision-breadcrumb a:hover {
  text-decoration: underline;
}
.precision-breadcrumb-sep {
  color: var(--muted);
  font-size: 11px;
  user-select: none;
}
.precision-breadcrumb-current {
  color: var(--sub);
  font-weight: 600;
}

/* ===== Pagination (サイズ拡大) ===== */
.precision-main .page-link {
  padding: 7px 14px;
}
```

- [ ] **Step 2: 開発サーバーで静的ファイルに変更が反映されているか確認**

ブラウザで任意のページを開き、DevToolsの Elements タブで `.empty-state` クラスの CSS が読み込まれていることを確認。

- [ ] **Step 3: コミット**

```bash
git add expenses/static/expenses/swiss.css
git commit -m "style: add empty-state, breadcrumb, pagination CSS components"
```

---

## Task 2: base.html にグローバル JS ユーティリティを追加

**Files:**
- Modify: `expenses/templates/expenses/base.html`

base.html の `{% block extra_js %}{% endblock %}` の直前にある `</script>` タグ（金額フィールド JS ブロックの末尾）の後、`{% block extra_js %}` の前に以下の `<script>` ブロックを追加する。

- [ ] **Step 1: base.html の `{% block extra_js %}{% endblock %}` の直前に以下を挿入**

```html
<script>
// ======= フォーム送信中の二重送信防止 =======
// 対象フォームの [data-submit-lock] ボタンを disabled にしてスピナーを表示する
// 呼び出し: bindFormSubmitLock(document.querySelector('form'))
(function(){
  window.bindFormSubmitLock = function(form) {
    if (!form || form._submitLockBound) return;
    form._submitLockBound = true;
    form.addEventListener('submit', function() {
      form.querySelectorAll('[data-submit-lock]').forEach(function(btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>送信中…';
      });
    });
  };
})();

// ======= ページ離脱警告（beforeunload） =======
// フォーム内の入力が変更されたら、ページ離脱時に確認ダイアログを表示する
// フォーム送信時は警告を出さない
// 呼び出し: bindFormDirtyGuard(document.querySelector('form'))
(function(){
  window.bindFormDirtyGuard = function(form) {
    if (!form || form._dirtyGuardBound) return;
    form._dirtyGuardBound = true;
    var dirty = false;
    form.querySelectorAll(
      'input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=file]), textarea, select'
    ).forEach(function(el) {
      el.addEventListener('change', function() { dirty = true; });
      el.addEventListener('input', function() { dirty = true; });
    });
    form.addEventListener('submit', function() { dirty = false; });
    window.addEventListener('beforeunload', function(e) {
      if (dirty) {
        e.preventDefault();
        e.returnValue = '';
        return '';
      }
    });
  };
})();

// ======= blur 時のリアルタイムバリデーション =======
// [data-required] → 空チェック
// [data-numeric]  → 数値形式チェック（カンマ区切り対応）
// 呼び出し: initFieldValidation(form)  ※動的追加行にも呼び出し可
(function(){
  function showError(el, msg) {
    el.classList.add('is-invalid');
    var fb = el.parentNode.querySelector('.invalid-feedback');
    if (!fb) {
      fb = document.createElement('div');
      fb.className = 'invalid-feedback';
      el.parentNode.appendChild(fb);
    }
    fb.textContent = msg;
  }
  function clearError(el) {
    el.classList.remove('is-invalid');
  }
  window.initFieldValidation = function(root) {
    var scope = root || document;
    scope.querySelectorAll('[data-required]').forEach(function(el) {
      if (el._requiredBound) return;
      el._requiredBound = true;
      el.addEventListener('blur', function() {
        if (!el.value.trim()) {
          showError(el, '必須項目です');
        } else {
          clearError(el);
        }
      });
      el.addEventListener('focus', function() { clearError(el); });
    });
    scope.querySelectorAll('[data-numeric]').forEach(function(el) {
      if (el._numericBound) return;
      el._numericBound = true;
      el.addEventListener('blur', function() {
        var val = el.value.replace(/,/g, '').trim();
        if (val !== '' && isNaN(parseFloat(val))) {
          showError(el, '数値を入力してください');
        } else {
          clearError(el);
        }
      });
      el.addEventListener('focus', function() { clearError(el); });
    });
  };
})();
</script>
```

- [ ] **Step 2: 動作確認（ブラウザコンソール）**

任意のページのブラウザコンソールで以下を実行し、`function` と表示されることを確認:

```javascript
typeof window.bindFormSubmitLock   // "function"
typeof window.bindFormDirtyGuard   // "function"
typeof window.initFieldValidation  // "function"
```

- [ ] **Step 3: コミット**

```bash
git add expenses/templates/expenses/base.html
git commit -m "feat: add bindFormSubmitLock, bindFormDirtyGuard, initFieldValidation to base.html"
```

---

## Task 3: 空状態デザインを統一する（home.html・expense_list.html・approval_list.html）

**Files:**
- Modify: `expenses/templates/expenses/home.html`
- Modify: `expenses/templates/expenses/expense_list.html`
- Modify: `expenses/templates/expenses/approval_list.html`

### home.html の変更

- [ ] **Step 1: home.html の3箇所ある「データなし」テキストを .empty-state に変更**

**変更前（承認待ちカード内）:**
```html
<p class="text-muted p-3 mb-0">承認待ちの申請はありません。</p>
```
**変更後:**
```html
<div class="empty-state" style="padding:24px;">
  <div class="empty-state-icon"><i class="fas fa-clock"></i></div>
  <div class="empty-state-title">承認待ちはありません</div>
</div>
```

**変更前（申請中カード内）:**
```html
<p class="text-muted p-3 mb-0">申請中の申請はありません。</p>
```
**変更後:**
```html
<div class="empty-state" style="padding:24px;">
  <div class="empty-state-icon"><i class="fas fa-paper-plane"></i></div>
  <div class="empty-state-title">申請中の申請はありません</div>
</div>
```

**変更前（下書きカード内）:**
```html
<p class="text-muted p-3 mb-0">下書きはありません。</p>
```
**変更後:**
```html
<div class="empty-state" style="padding:24px;">
  <div class="empty-state-icon"><i class="fas fa-edit"></i></div>
  <div class="empty-state-title">下書きはありません</div>
</div>
```

### expense_list.html の変更

- [ ] **Step 2: expense_list.html の空状態ブロックを変更**

**変更前:**
```html
{% else %}
    <div class="text-center py-5">
        <div class="mb-4">
            <i class="fas fa-file-invoice-dollar fa-4x text-muted"></i>
        </div>
        {% if status_filter or date_from or date_to or keyword %}
            <h4 class="text-muted">条件に一致する申請がありません</h4>
            <p class="text-muted">フィルターを変更してみてください。</p>
            <a href="{% url 'expenses:expense_list' %}" class="btn btn-outline-secondary me-2">
                <i class="fas fa-times"></i> フィルタークリア
            </a>
        {% else %}
            <h4 class="text-muted">経費申請はありません</h4>
            <p class="text-muted">まだ申請がありません。新規申請を作成しましょう。</p>
        {% endif %}
        <a href="{% url 'expenses:expense_create' %}" class="btn btn-primary">
            <i class="fas fa-plus"></i> 新規申請
        </a>
    </div>
{% endif %}
```
**変更後:**
```html
{% else %}
    <div class="empty-state">
        <div class="empty-state-icon"><i class="fas fa-file-invoice-dollar"></i></div>
        {% if status_filter or date_from or date_to or keyword %}
            <div class="empty-state-title">条件に一致する申請がありません</div>
            <div class="empty-state-desc">フィルターを変更してみてください。</div>
            <a href="{% url 'expenses:expense_list' %}" class="btn btn-outline-secondary me-2">
                <i class="fas fa-times"></i> フィルタークリア
            </a>
        {% else %}
            <div class="empty-state-title">経費申請はありません</div>
            <div class="empty-state-desc">まだ申請がありません。新規申請を作成しましょう。</div>
        {% endif %}
        <a href="{% url 'expenses:expense_create' %}" class="btn btn-primary">
            <i class="fas fa-plus"></i> 新規申請
        </a>
    </div>
{% endif %}
```

### approval_list.html の変更

- [ ] **Step 3: approval_list.html の空状態ブロックを変更**

**変更前:**
```html
{% else %}
    <div class="text-center py-5">
        <div class="mb-4">
            <i class="fas fa-clipboard-check fa-4x text-muted"></i>
        </div>
        {% if status_filter or date_from or date_to or keyword %}
            <h4 class="text-muted">条件に一致する申請がありません</h4>
            <a href="{% url 'expenses:approval_list' %}" class="btn btn-outline-secondary">
                <i class="fas fa-times"></i> フィルタークリア
            </a>
        {% else %}
            <h4 class="text-muted">承認待ちの申請はありません</h4>
            <p class="text-muted">現在、承認待ちの経費申請はありません。</p>
            <a href="{% url 'expenses:home' %}" class="btn btn-primary">
                <i class="fas fa-home"></i> ホームに戻る
            </a>
        {% endif %}
    </div>
{% endif %}
```
**変更後:**
```html
{% else %}
    <div class="empty-state">
        <div class="empty-state-icon"><i class="fas fa-clipboard-check"></i></div>
        {% if status_filter or date_from or date_to or keyword %}
            <div class="empty-state-title">条件に一致する申請がありません</div>
            <div class="empty-state-desc">フィルターを変更してみてください。</div>
            <a href="{% url 'expenses:approval_list' %}" class="btn btn-outline-secondary">
                <i class="fas fa-times"></i> フィルタークリア
            </a>
        {% else %}
            <div class="empty-state-title">承認待ちの申請はありません</div>
            <div class="empty-state-desc">現在、承認待ちの経費申請はありません。</div>
            <a href="{% url 'expenses:home' %}" class="btn btn-primary">
                <i class="fas fa-home"></i> ホームに戻る
            </a>
        {% endif %}
    </div>
{% endif %}
```

- [ ] **Step 4: ブラウザで各画面の空状態を確認**

各一覧ページでデータが0件の状態（またはフィルターで0件にした状態）にして、アイコン・タイトル・説明文が統一されたスタイルで表示されることを確認。

- [ ] **Step 5: コミット**

```bash
git add expenses/templates/expenses/home.html \
        expenses/templates/expenses/expense_list.html \
        expenses/templates/expenses/approval_list.html
git commit -m "feat: unify empty state design across list pages"
```

---

## Task 4: ページネーション改善（expense_list.html・approval_list.html）

**Files:**
- Modify: `expenses/templates/expenses/expense_list.html`
- Modify: `expenses/templates/expenses/approval_list.html`

### expense_list.html の変更

- [ ] **Step 1: expense_list.html のページネーション `<nav>` ブロックを変更**

**変更前:**
```html
<nav class="mt-3" aria-label="ページネーション">
    <ul class="pagination pagination-sm justify-content-center mb-0">
```
**変更後:**
```html
<div class="d-flex justify-content-between align-items-center mt-3 px-1">
    <small class="text-muted">
        全{{ page_obj.paginator.count }}件中
        {{ page_obj.start_index }}〜{{ page_obj.end_index }}件を表示
    </small>
    <nav aria-label="ページネーション">
    <ul class="pagination justify-content-center mb-0">
```

また、`</nav>` の直前に `</nav>` 外側のdivを閉じるため、ページネーション `</ul>` の後を以下に変更:

**変更前:**
```html
    </ul>
</nav>
```
**変更後:**
```html
    </ul>
    </nav>
</div>
```

### approval_list.html の変更

- [ ] **Step 2: approval_list.html に同じ変更を適用**

**変更前:**
```html
<nav class="mt-3" aria-label="ページネーション">
    <ul class="pagination pagination-sm justify-content-center mb-0">
```
**変更後:**
```html
<div class="d-flex justify-content-between align-items-center mt-3 px-1">
    <small class="text-muted">
        全{{ page_obj.paginator.count }}件中
        {{ page_obj.start_index }}〜{{ page_obj.end_index }}件を表示
    </small>
    <nav aria-label="ページネーション">
    <ul class="pagination justify-content-center mb-0">
```

**変更前:**
```html
    </ul>
</nav>
```
**変更後:**
```html
    </ul>
    </nav>
</div>
```

- [ ] **Step 3: 件数が2ページ以上あるデータで確認**

「全N件中 X〜Y件を表示」の件数インジケーターが表示されること、ページネーションボタンが以前より大きく表示されることをブラウザで確認。

- [ ] **Step 4: コミット**

```bash
git add expenses/templates/expenses/expense_list.html \
        expenses/templates/expenses/approval_list.html
git commit -m "feat: improve pagination UX with count indicator and larger buttons"
```

---

## Task 5: ブレッドクラムを追加（expense_detail・expense_edit・approval_detail）

**Files:**
- Modify: `expenses/templates/expenses/expense_detail.html`
- Modify: `expenses/templates/expenses/expense_edit.html`
- Modify: `expenses/templates/expenses/approval_detail.html`

### expense_detail.html の変更

- [ ] **Step 1: expense_detail.html の `page-head` 直前にブレッドクラムを挿入**

`<div class="page-head mb-4">` の直前に以下を追加:

```html
<nav class="precision-breadcrumb mb-1" aria-label="パンくずリスト">
    <a href="{% url 'expenses:expense_list' %}">経費申請一覧</a>
    <span class="precision-breadcrumb-sep">›</span>
    <span class="precision-breadcrumb-current">#{{ expense.expense_main_id }} 申請詳細</span>
</nav>
```

### expense_edit.html の変更

- [ ] **Step 2: expense_edit.html の `<h2 class="mb-4">` を `page-head` 形式に変更し、ブレッドクラムを挿入**

**変更前:**
```html
<div class="container">
    <h2 class="mb-4">経費申請編集</h2>
```
**変更後:**
```html
<div class="container">
    <nav class="precision-breadcrumb mb-1" aria-label="パンくずリスト">
        <a href="{% url 'expenses:expense_list' %}">経費申請一覧</a>
        <span class="precision-breadcrumb-sep">›</span>
        <span class="precision-breadcrumb-current">#{{ expense.expense_main_id }} 編集</span>
    </nav>
    <div class="page-head mb-4">
        <h2 class="page-title">
            <span class="pt-ico"><i class="fas fa-edit"></i></span>
            経費申請編集
        </h2>
    </div>
```

### approval_detail.html の変更

- [ ] **Step 3: approval_detail.html の `page-head` 直前にブレッドクラムを挿入**

`<div class="page-head mb-4">` の直前に以下を追加:

```html
<nav class="precision-breadcrumb mb-1" aria-label="パンくずリスト">
    <a href="{% url 'expenses:approval_list' %}">承認待ち一覧</a>
    <span class="precision-breadcrumb-sep">›</span>
    <span class="precision-breadcrumb-current">#{{ expense.expense_main_id }} 承認詳細</span>
</nav>
```

- [ ] **Step 4: 各ページでブレッドクラムの表示を確認**

各詳細・編集画面でページタイトルの上部に「一覧 › #ID ページ名」の形式でブレッドクラムが表示されること、一覧リンクが正しく機能することを確認。

- [ ] **Step 5: コミット**

```bash
git add expenses/templates/expenses/expense_detail.html \
        expenses/templates/expenses/expense_edit.html \
        expenses/templates/expenses/approval_detail.html
git commit -m "feat: add breadcrumb navigation to detail and edit pages"
```

---

## Task 6: expense_form.html に二重送信防止・エラースクロール・beforeunload・blur バリデーションを追加

**Files:**
- Modify: `expenses/templates/expenses/expense_form.html`

### 二重送信防止

- [ ] **Step 1: expense_form.html の送信ボタンに `data-submit-lock` を追加**

**変更前（line 343-344付近）:**
```html
<button type="submit" name="action" value="draft" class="btn btn-outline-primary me-2">下書き保存</button>
<button type="submit" name="action" value="submit" class="btn btn-primary" id="submit-btn">申請する</button>
```
**変更後:**
```html
<button type="submit" name="action" value="draft" class="btn btn-outline-primary me-2" data-submit-lock>下書き保存</button>
<button type="submit" name="action" value="submit" class="btn btn-primary" id="submit-btn" data-submit-lock>申請する</button>
```

### エラー時の自動スクロール

- [ ] **Step 2: expense_form.html の `{% block extra_js %}` 内の先頭（既存JSより前）に追加**

`{% block extra_js %}` の直後、`<script>` タグの先頭に以下を追加:

```javascript
// エラーがある場合はページ読み込み時に先頭のエラーまでスクロール
document.addEventListener('DOMContentLoaded', function() {
    var firstError = document.querySelector('.alert-danger');
    if (firstError) {
        firstError.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
});
```

### beforeunload とリアルタイムバリデーション

- [ ] **Step 3: expense_form.html の `{% block extra_js %}` 内、既存コードの後に追加**

既存の `document.getElementById('submit-btn').addEventListener('click', ...)` のブロックの後に以下を追加:

```javascript
// ページ離脱警告
document.addEventListener('DOMContentLoaded', function() {
    var form = document.querySelector('form[enctype]');
    if (form) {
        window.bindFormDirtyGuard(form);
        window.bindFormSubmitLock(form);
    }
});

// blur バリデーション（date・amount フィールド）
document.addEventListener('DOMContentLoaded', function() {
    window.initFieldValidation(document);
});
// 動的追加行にも適用（既存の addDetailForm 関数がある場合に備えたフック）
var _origInitAmountFields = window.initAmountFields;
window.initAmountFields = function(root) {
    if (_origInitAmountFields) _origInitAmountFields(root);
    window.initFieldValidation(root || document);
};
```

### date・amount フィールドに data 属性を付与

- [ ] **Step 4: formset の date フィールドに `data-required` を追加**

expense_form.html 内で `detail_form.date` を render している箇所（line 78-88付近）を確認し、日付 input に `data-required` 属性を付与するため、以下のパターンで変更:

**変更前（エラーなし時の date フィールド）:**
```html
{{ detail_form.date|add_class:"form-control" }}
```
**変更後:**
```html
{{ detail_form.date|add_class:"form-control"|attr:"data-required:true" }}
```

amount フィールド（line 90-96付近）も同様:

**変更前:**
```html
{{ detail_form.amount|add_class:"form-control"|attr:"inputmode:numeric"|attr:"type:text"|attr:"data-amount-input:1" }}
```
**変更後:**
```html
{{ detail_form.amount|add_class:"form-control"|attr:"inputmode:numeric"|attr:"type:text"|attr:"data-amount-input:1"|attr:"data-numeric:true" }}
```

- [ ] **Step 5: ブラウザで動作確認**

1. 新規申請フォームを開き、何か入力してブラウザバックボタンを押す → 「このページを離れますか？」警告が出ることを確認
2. 申請ボタンを押すと「送信中…」に変わりボタンが無効化されることを確認（※送信エラー時はリロードで復元）
3. date フィールドを一度クリックして空のままフォーカスアウト → 「必須項目です」が表示されることを確認
4. バリデーションエラーがある状態でページをリロードして、エラーアラートまで自動スクロールされることを確認

- [ ] **Step 6: コミット**

```bash
git add expenses/templates/expenses/expense_form.html
git commit -m "feat: add submit lock, error scroll, beforeunload, blur validation to expense_form"
```

---

## Task 7: travel_expense_form.html に同様の改善を追加

**Files:**
- Modify: `expenses/templates/expenses/travel_expense_form.html`

### 二重送信防止

- [ ] **Step 1: travel_expense_form.html の送信ボタンに `data-submit-lock` を追加**

**変更前（line 521-522付近）:**
```html
<button type="submit" name="action" value="draft" class="btn btn-outline-primary me-2">下書き保存</button>
<button type="submit" name="action" value="submit" class="btn btn-primary" id="submit-btn">申請する</button>
```
**変更後:**
```html
<button type="submit" name="action" value="draft" class="btn btn-outline-primary me-2" data-submit-lock>下書き保存</button>
<button type="submit" name="action" value="submit" class="btn btn-primary" id="submit-btn" data-submit-lock>申請する</button>
```

### エラー時の自動スクロール

- [ ] **Step 2: travel_expense_form.html の `{% block extra_js %}` 内の先頭に追加**

```javascript
// エラーがある場合はページ読み込み時に先頭のエラーまでスクロール
document.addEventListener('DOMContentLoaded', function() {
    var firstError = document.querySelector('.alert-danger');
    if (firstError) {
        firstError.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
});
```

### beforeunload と submit lock の有効化

- [ ] **Step 3: travel_expense_form.html の既存 `document.getElementById('submit-btn').addEventListener('click', ...)` のブロックの後に追加**

```javascript
// ページ離脱警告 + 二重送信防止
document.addEventListener('DOMContentLoaded', function() {
    var form = document.querySelector('form[enctype]');
    if (form) {
        window.bindFormDirtyGuard(form);
        window.bindFormSubmitLock(form);
    }
});
```

- [ ] **Step 4: ブラウザで出張旅費フォームの動作確認**

1. 出張旅費入力中にタブを閉じようとして警告が出ることを確認
2. 申請ボタン押下時にスピナーが表示されることを確認
3. エラー付きリロードで自動スクロールを確認

- [ ] **Step 5: コミット**

```bash
git add expenses/templates/expenses/travel_expense_form.html
git commit -m "feat: add submit lock, error scroll, beforeunload to travel_expense_form"
```

---

## Task 8: 承認確認ダイアログを Bootstrap モーダルに変更

**Files:**
- Modify: `expenses/templates/expenses/approval_detail.html`

- [ ] **Step 1: 承認フォームの直前にモーダル HTML を追加**

`<!-- 承認フォーム -->` の直前に以下のモーダルHTMLを挿入:

```html
<!-- 承認確認モーダル -->
<div class="modal fade" id="approvalConfirmModal" tabindex="-1" aria-labelledby="approvalModalTitle" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content" style="border-radius:8px; overflow:hidden;">
            <div class="modal-header" id="approvalModalHeader" style="border-bottom:1px solid #e5e7eb;">
                <h5 class="modal-title" id="approvalModalTitle" style="font-size:15px; font-weight:700;"></h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="閉じる"></button>
            </div>
            <div class="modal-body" style="font-size:14px;">
                <p id="approvalModalMessage" class="mb-2"></p>
                <div id="approvalModalCommentPreview"
                     class="p-2 rounded small border-start border-3 border-secondary bg-light"
                     style="display:none; font-size:13px; word-break:break-word;"></div>
            </div>
            <div class="modal-footer" style="border-top:1px solid #e5e7eb;">
                <button type="button" class="btn btn-outline-secondary btn-sm" data-bs-dismiss="modal">キャンセル</button>
                <button type="button" class="btn btn-sm" id="approvalModalConfirm" style="min-width:80px;">実行</button>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 2: approval_detail.html 末尾の `<script>` ブロックを新しい実装に完全置き換え**

**変更前（既存の confirm ロジック）:**
```javascript
<script>
// フォーム送信時の確認
document.querySelector('form').addEventListener('submit', function(e) {
    const status = document.querySelector('select[name="status"]').value;
    const comment = document.querySelector('textarea[name="comment"]').value;
    
    let message = '';
    if (status === 'APPROVED') {
        message = 'この申請を承認しますか？';
    } else if (status === 'REJECTED') {
        message = 'この申請を却下しますか？';
    } else if (status === 'RETURNED') {
        message = 'この申請を差戻ししますか？';
    }
    
    if (!confirm(message)) {
        e.preventDefault();
    }
});
</script>
```

**変更後:**
```javascript
<script>
(function() {
    var approvalForm = document.querySelector('form[method="post"]');
    var modal = document.getElementById('approvalConfirmModal');
    var bsModal = new bootstrap.Modal(modal);

    var CONFIG = {
        'APPROVED': {
            title:   '✓ 承認の確認',
            message: 'この申請を承認します。よろしいですか？',
            headerBg: '#f0fdf4',
            headerColor: '#166534',
            btnClass: 'btn-success',
            borderClass: 'border-success'
        },
        'REJECTED': {
            title:   '✕ 却下の確認',
            message: 'この申請を却下します。この操作は取り消せません。',
            headerBg: '#fef2f2',
            headerColor: '#991b1b',
            btnClass: 'btn-danger',
            borderClass: 'border-danger'
        },
        'RETURNED': {
            title:   '↩ 差戻しの確認',
            message: 'この申請を差し戻します。申請者に再編集を依頼します。',
            headerBg: '#fffbeb',
            headerColor: '#92400e',
            btnClass: 'btn-warning',
            borderClass: 'border-warning'
        }
    };

    // 送信ボタン押下時: モーダル表示
    approvalForm.addEventListener('submit', function(e) {
        e.preventDefault();
        var status  = approvalForm.querySelector('select[name="status"]').value;
        var comment = approvalForm.querySelector('textarea[name="comment"]').value.trim();
        var cfg = CONFIG[status];
        if (!cfg) { approvalForm.submit(); return; }

        // モーダルの内容をセット
        var header  = document.getElementById('approvalModalHeader');
        var title   = document.getElementById('approvalModalTitle');
        var message = document.getElementById('approvalModalMessage');
        var preview = document.getElementById('approvalModalCommentPreview');
        var confirmBtn = document.getElementById('approvalModalConfirm');

        header.style.background = cfg.headerBg;
        title.style.color  = cfg.headerColor;
        title.textContent  = cfg.title;
        message.textContent = cfg.message;

        // コメントプレビュー
        if (comment) {
            preview.textContent = '「' + comment + '」';
            preview.style.display = 'block';
            preview.className = 'p-2 rounded small border-start border-3 bg-light ' + cfg.borderClass;
        } else {
            preview.style.display = 'none';
        }

        // 実行ボタンのスタイル
        confirmBtn.className = 'btn btn-sm ' + cfg.btnClass;
        confirmBtn.textContent = '実行';

        bsModal.show();
    });

    // モーダルの「実行」ボタン押下時: 実際に送信
    document.getElementById('approvalModalConfirm').addEventListener('click', function() {
        bsModal.hide();
        // data-submit-lock ボタンをロック
        approvalForm.querySelectorAll('[data-submit-lock]').forEach(function(btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>送信中…';
        });
        approvalForm.submit();
    });
})();
</script>
```

- [ ] **Step 3: 承認フォームの「処理を実行」ボタンに `data-submit-lock` を追加**

**変更前:**
```html
<button type="submit" class="btn btn-success w-100">
    <i class="fas fa-check"></i>
    処理を実行
</button>
```
**変更後:**
```html
<button type="submit" class="btn btn-success w-100" data-submit-lock>
    <i class="fas fa-check"></i>
    処理を実行
</button>
```

- [ ] **Step 4: ブラウザで動作確認**

1. 「承認」を選択して「処理を実行」→ 緑ヘッダーのモーダルが表示されることを確認
2. 「却下」を選択 → 赤ヘッダーのモーダルが表示されることを確認
3. 「差戻し」を選択 → 黄ヘッダーのモーダルが表示されることを確認
4. コメント入力後に「承認」選択 → モーダル内にコメントのプレビューが表示されることを確認
5. 「キャンセル」ボタンでモーダルが閉じることを確認
6. 「実行」ボタンで実際に承認処理が実行されることを確認

- [ ] **Step 5: コミット**

```bash
git add expenses/templates/expenses/approval_detail.html
git commit -m "feat: replace window.confirm with Bootstrap modal for approval confirmation"
```

---

## 完了チェックリスト

全タスク完了後、以下を確認:

- [ ] ダッシュボード（home）でデータ0件時の空状態が統一されている
- [ ] 経費一覧・承認一覧でページネーションが大きく、件数が表示されている
- [ ] 申請詳細・編集・承認詳細でブレッドクラムが表示されている
- [ ] 申請フォームで入力後にタブを閉じようとすると警告が出る
- [ ] 申請フォームで「申請する」を押すとボタンがスピナーに変わる
- [ ] 承認詳細で「処理を実行」を押すとカラーコード付きのモーダルが出る
- [ ] バリデーションエラー付きでページリロード時、エラーまで自動スクロールされる
