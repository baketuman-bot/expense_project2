# フロントエンド UX 改善 設計ドキュメント

- **作成日:** 2026-05-26
- **対象:** 費用精算Webアプリ（expense_project2）
- **スコープ:** 申請者・承認者両ロールの操作体験改善（8項目）

---

## 対象改善項目

| # | タイトル | 影響範囲 |
|---|---|---|
| 1 | フォーム送信中の二重送信防止 | 全フォーム |
| 2 | フォームエラー時の自動スクロール | 申請フォーム |
| 3 | 承認確認ダイアログの改善 | 承認詳細 |
| 6 | リアルタイムバリデーション | 申請フォーム |
| 7 | beforeunload による消失防止 | 申請フォーム |
| 8 | 空状態デザインの統一 | 全一覧画面 |
| 9 | ページネーションUX改善 | 一覧画面 |
| 10 | ブレッドクラム追加 | 詳細・編集画面 |

---

## 各項目の設計

### 1. フォーム送信中の二重送信防止

**問題:** submit を2回押すと申請が重複作成されるリスクがある。送信中のフィードバックがない。

**設計:**
- `base.html` のグローバルJSに `bindFormSubmitLock(form)` 関数を追加
- submit イベント発火時: 送信ボタンを `disabled` にし、テキストをスピナーアイコン＋「送信中…」に変更
- 対象: `expense_form.html`, `travel_expense_form.html`, `approval_detail.html`, `feedback_form.html`
- DOMContentLoaded 時に全 `form[method="post"]` に自動適用

**実装ファイル:**
- `expenses/templates/expenses/base.html` — JS追加
- 各フォームテンプレートのsubmitボタンに `data-submit-lock` 属性付与（対象を絞るため）

---

### 2. フォームエラー時の自動スクロール

**問題:** 1000行超のフォームでエラー発生時、ユーザーが既に下にスクロールしていると上部のエラーアラートに気づかない。

**設計:**
- テンプレート側で `{% if error_message or formset.errors %}` が真の場合、インラインJSで `document.querySelector('.alert-danger').scrollIntoView({behavior:'smooth', block:'start'})` を実行
- `base.html` の `extra_js` ブロックより前に実行されるよう配置
- 対象: `expense_form.html`, `travel_expense_form.html`

---

### 3. 承認確認ダイアログの改善

**問題:** `window.confirm()` はブラウザ依存の粗いUI。承認・却下・差戻しが同じダイアログになっている。

**設計:**
- `approval_detail.html` 内の `window.confirm()` を Bootstrap Modal に置き換え
- モーダル構成:
  - **承認:** ヘッダー緑（`#166534` 背景 `#f0fdf4`）、「この申請を承認します」
  - **却下:** ヘッダー赤（`#991b1b` 背景 `#fef2f2`）、「この申請を却下します。この操作は取り消せません」
  - **差戻し:** ヘッダー黄（`#92400e` 背景 `#fffbeb`）、「この申請を差し戻します」
- コメントを入力している場合はモーダル内にもプレビュー表示
- モーダルの「実行」ボタンを押したときに実際のフォームsubmitを実行

---

### 6. リアルタイムバリデーション

**問題:** `novalidate` でブラウザ標準バリデーション無効化済み。代替バリデーションがなく、送信して初めてエラーが分かる。

**設計:**
- `blur` イベントで必須フィールドチェック + 数値形式チェックを実行
- エラー時: フィールドに `is-invalid` クラス付与 + `.invalid-feedback` でインラインエラーメッセージ表示
- フォーカス時にエラー消去
- 対象フィールド: `date`（必須）、`amount`（必須・数値）、`shiharaisaki`（任意だが文字数）
- `base.html` にグローバル関数 `initFieldValidation(form)` を追加
- swiss.css には `.is-invalid` スタイルが既に定義済み（追加CSS不要）

---

### 7. beforeunload による消失防止

**問題:** 申請フォーム入力途中にブラウザバック・タブ閉じを行うと入力内容がすべて消える。

**設計:**
- フォーム内の `input`, `textarea`, `select` に `change` イベントを監視
- 変更が発生したら `window._formDirty = true` をセット
- `beforeunload` イベントで `_formDirty` が true なら警告を出す
- フォーム submit 時に `_formDirty = false` にリセット（警告を出さない）
- 対象: `expense_form.html`, `travel_expense_form.html`
- `base.html` にグローバル関数 `bindFormDirtyGuard(form)` を追加

---

### 8. 空状態デザインの統一

**問題:** データなし時のUIが画面によってバラバラ（テキストのみ、アイコン付き、カード内外で不統一）。

**設計:**
- `swiss.css` に `.empty-state` コンポーネントを追加:
  ```
  .empty-state { text-align: center; padding: 48px 24px; color: var(--sub); }
  .empty-state-icon { font-size: 40px; margin-bottom: 16px; color: var(--muted); }
  .empty-state-title { font-size: 15px; font-weight: 600; margin-bottom: 6px; }
  .empty-state-desc { font-size: 13px; margin-bottom: 20px; }
  ```
- 適用対象テンプレート: `expense_list.html`, `approval_list.html`, `home.html`（各カード内）

---

### 9. ページネーションUX改善

**問題:** 現在のページ位置・総件数の表示が小さく見づらい。ページングボタンが小さい。

**設計:**
- フィルターバー右端（または一覧カードヘッダー内）に `XX件中 YY〜ZZ件を表示` の件数インジケーターを追加
- `pagination-sm` クラスを通常サイズ `pagination` に変更
- swiss.css の `.precision-main .page-link` のパディングを現在 `5px 10px` → `7px 14px` に拡大
- 対象: `expense_list.html`, `approval_list.html`

---

### 10. ブレッドクラム追加

**問題:** 深いページ（承認詳細・申請詳細・編集）で現在地が分かりにくい。

**設計:**
- `page-head` の `h2` 上部にブレッドクラムを配置
- swiss.css に `.precision-breadcrumb` スタイルを追加（14px、区切り `›`、現在ページは非リンク）
- 対象画面と表示内容:
  - `approval_detail.html`: `承認待ち一覧 › #ID 承認詳細`
  - `expense_detail.html`: `経費申請一覧 › #ID 申請詳細`
  - `expense_edit.html`: `経費申請一覧 › #ID 編集`

---

## 実装方針

- **JS:** 新規関数はすべて `base.html` のグローバルJSブロックに追加。各テンプレートから呼び出す。
- **CSS:** 新規スタイルは `swiss.css` の末尾に追記。
- **テンプレート:** 既存の構造を最小限の変更で修正。大規模リファクタは行わない。
- **後方互換:** Django側（views.py, forms.py）の変更は原則なし。

---

## 変更対象ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `swiss.css` | `.empty-state`, `.precision-breadcrumb`, ページネーションパディング |
| `base.html` | `bindFormSubmitLock`, `initFieldValidation`, `bindFormDirtyGuard` JS追加 |
| `expense_form.html` | エラースクロール, バリデーション, beforeunload, 二重送信防止 |
| `travel_expense_form.html` | 同上 |
| `approval_detail.html` | 確認モーダル, 二重送信防止 |
| `expense_list.html` | 空状態統一, ページネーション改善, 件数インジケーター |
| `approval_list.html` | 空状態統一, ページネーション改善 |
| `home.html` | 空状態統一 |
| `expense_detail.html` | ブレッドクラム |
| `expense_edit.html` | ブレッドクラム |
