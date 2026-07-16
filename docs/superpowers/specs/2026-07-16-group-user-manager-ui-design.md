# グループ/ユーザーマネージャーUI 設計

日付: 2026-07-16
参考元: GSession 稟議グループウェア 管理者設定「グループマネージャー(usr010/011/020)」「ユーザマネージャー(usr030/031)」(`tmp/gsession_src`)

## 背景・目的

現在の `/settings/master/m_group/`・`/settings/master/m_user/` は MASTER_REGISTRY による汎用マスタ画面（フラットなテーブル＋フォーム）で、以下が不便:

- 部署の階層構造（`upper_group_cd`）が一覧から読み取れない
- ユーザーが増えると絞り込み手段がない（部門・役職・有効/無効で探せない）
- どのユーザーがどの部署（M_BelongTo）に所属しているか一覧できず、所属させ忘れによる「承認者候補に出てこない」問題に気づきにくい

GSession のマネージャーUIの構造（グループ＝階層ツリー、ユーザー＝検索絞り込み＋操作）を、本アプリの swiss.css デザインに適合させて導入する。

## スコープ（決定事項）

| 論点 | 決定 |
|---|---|
| 機能範囲 | ツリー＋検索UIの基本機能のみ |
| 五十音インデックス | M_Userにカナ欄がないため**フィルタ検索で代替**（カナ列追加はしない） |
| 配置 | **既存URLを差し替え**（`/settings/master/m_group/`・`/settings/master/m_user/` の一覧のみ専用画面化） |
| UIデザイン | swiss.css の既存パターンに適合（GSession忠実再現はしない） |
| 追加機能 | ①ユーザー一覧に所属部署列＋所属部署フィルタ、②グループツリーに所属ユーザー展開表示 の**両方を含める** |

**スコープ外**: 所属ユーザーの一括割当（デュアルリストボックス）、CSVインポート/エクスポート、グループ管理者設定、ユーザー削除ボタン（無効化で代替）、M_Group編集フォームでの循環参照バリデーション。

## 全体構成

- `settings_master_list` ビューの冒頭で key が `m_group` / `m_user` のとき専用ビューへ委譲する。他のマスタキーは従来の汎用画面のまま。
- 追加・編集フォームは既存の `settings_master_create` / `settings_master_edit`（modelform_factory）をそのまま再利用。**一覧画面のみ差し替え**。
- ビューは `expenses/views_org_manager.py` を新設して切り出し（規約: ビュー肥大時は別ファイル）。
- テンプレートは `expenses/templates/expenses/group_manager_list.html` / `user_manager_list.html` の2枚。
- **DB変更・マイグレーションなし**（既存モデルの読み書きのみ）。

## グループマネージャー（部署ツリー）

- `M_Group` 全件を `upper_group_cd` で木構造化（Python再帰）し、インデント付きツリーで表示。
- 各行: 部署名（コード）＋所属人数バッジ＋ `[配下に追加]` `[編集]` `[削除]`。
- 人数バッジクリックで、その部署の所属ユーザー名（＋社員番号）を行下にアコーディオン展開（Bootstrap collapse、AJAXなし・ページ表示時に一括埋め込み）。
- `[配下に追加]` は既存の新規作成フォームへ `?parent=<group_cd>` を渡し、`upper_group_cd` を初期値セット。`settings_master_create` 側でGETパラメータからinitialを設定する小改修を行う。
- 削除は既存の `settings_master_delete` のまま。`M_BelongTo.group_cd` が PROTECT のため所属者がいる部署は削除不可（既存のエラーハンドリングに乗る）。

### 防御的処理（木構築）

- 循環参照: visited 集合で検出し、検出したノードはルート扱いで表示（無限ループ防止）。
- orphan（`upper_group_cd` が存在しない部署コードを指す）: ルート扱いで表示し、行に注意表示。

## ユーザーマネージャー（フィルタ＋テーブル）

- フィルタバー: 部門▼・役職▼・**所属部署▼**（選択部署に直接所属するユーザーのみ。配下部署は含めない）・状態▼（すべて/有効/無効、**デフォルト有効**）・キーワード（社員番号 or 氏名の icontains）。
- テーブル列: 社員番号・氏名・部門・役職・**所属部署**（M_BelongTo をカンマ区切り、未所属は「（未所属）」を警告色表示）・状態バッジ・操作。
- ページング: 50件/ページ（既存パターン）。
- 操作: `[編集]`（既存 `master_edit` へ）、`[無効化]`/`[有効化]` トグル。
- トグルは AJAX POST（`settlement_toggle` と同パターン）。URL: `/settings/master/m_user/<pk>/toggle_active/`。CSRF・POST限定・ログイン必須。
- **削除ボタンは置かない**。本番DBで申請データがFK参照するため、退職者等は `is_active=False`（無効化）で運用する。

## 権限・デザイン

- 権限は既存のマスタ設定画面と同一（追加の権限制御なし）。
- swiss.css の既存パターンを踏襲: `page-head`/`page-title`、テーブル行ホバー（左アクセントストライプ）、ステータスピル、人数バッジ。

## 実装ファイル一覧

| ファイル | 変更 |
|---|---|
| `expenses/views_org_manager.py` | 新規: `group_manager_list`, `user_manager_list`, `user_toggle_active` |
| `expenses/views.py` | `settings_master_list` に m_group/m_user の委譲分岐、`settings_master_create` にGET initial対応、`from .views_org_manager import ...` |
| `expenses/urls.py` | `user_toggle_active` のURL追加 |
| `expenses/templates/expenses/group_manager_list.html` | 新規 |
| `expenses/templates/expenses/user_manager_list.html` | 新規 |

## テスト方針

- 本番DB直結のため、ランタイム検証は読み取り専用で行う（`verify` スキル手順に従う）。
- 木構築ロジック（循環・orphan含む）は純粋関数として切り出し、ユニットテスト可能な形にする。テスト実行時は `test_expense_db`＋`--keepdb`（`DJANGO_TEST_DB_NAME=expense_db` は厳禁）。
- トグルAPIの書き込み検証は自分のテストユーザー等、影響のないレコードで行う。
