# UI改善タスク（Claude Code用プロンプト）

以下のUI改善を実施して。対象はDjangoテンプレート・CSS・JSのみで、モデル変更・マイグレーション・DB操作は一切不要。CLAUDE.mdの本番DB注意事項を厳守（破壊的操作禁止）。
作業は下記のタスク順に1タスクずつ実施し、タスクごとに動作確認ポイントを報告して。

## タスク1: 承認処理のボタン直接化【最優先】

対象: `expenses/templates/expenses/approval_detail.html`（承認フォーム部分、412行目付近）

現状は「処理選択」セレクトボックス＋緑の「処理を実行」ボタン。これを廃止し、3つの明示的なボタンに変更する:

- 「承認する」: btn-success
- 「差戻し」: btn-outline-warning
- 「却下」: btn-outline-danger

要件:
- 既存の確認モーダル実装（同テンプレート620行目付近、btnClass分岐あり）を流用し、各ボタン押下→確認モーダル→実行のフローにする
- POST内容（form.statusの値）は現状のビューロジックと互換を保つこと。views.pyの`approval_detail`が受け取る値を確認し、hidden inputにボタンに応じた値をセットして送信する方式にする
- コメント欄は現状のまま3ボタンの上に配置。却下・差戻し時はコメント入力を推奨する文言を確認モーダルに表示
- `data-submit-lock`（二重送信防止）を全ボタンに適用
- `settings_approval_detail.html`（承認管理の強制操作画面）にも同様のUIがあれば同じ方式に統一

## タスク2: ブラウザタブのタイトル修正

対象: `expenses/templates/expenses/base.html`

`<title>経費精算システム</title>` が固定のため、子テンプレートの `{% block title %}` が無視されている。

- `<title>{% block title %}経費精算システム{% endblock %} </title>` 形式に変更（子側は「承認待ち一覧 | 経費精算システム」のように接尾辞付きが望ましいので、`{% block title %}{% endblock %}経費精算システム` のような構成を検討）
- 主要画面（home, expense_list, expense_form, expense_detail, approval_list, approval_detail, settlement系, settings系, feedback系, assets系）に適切な `{% block title %}` を追加

## タスク3: home.htmlのロール判定バグ修正

対象: `expenses/templates/expenses/home.html` 18行目

`{% if user.role in 'approver,accountant,final_approver' %}` は旧方式で、M_UserRole/has_role方式（CLAUDE.md参照）と不整合。base.htmlで使用している `|has_role:` フィルタ（expense_extras）を使った判定に修正する。判定対象ロールは views.py の home ビューで `pending_approvals` を組み立てている条件と整合させること。

## タスク4: 申請フォームに固定アクションバー＋明細合計表示

対象: `expenses/templates/expenses/expense_form.html`、`travel_expense_form.html`、`expenses/static/expenses/swiss.css`

- 画面下部に固定（position: fixed; bottom: 0; サイドバー幅 `var(--precision-sidebar-width)` 分を左にオフセット）のアクションバーを追加
- バー内容: 左側に「明細合計: ¥XX,XXX」のライブ表示、右側に既存のキャンセル／下書き保存／申請するボタンを移動
- 合計は `[data-amount-input]` フィールドのinputイベントで再計算（カンマ除去は base.html の既存ユーティリティと同じ方式: `parseFloat(v.replace(/,/g,''))`）
- travel_expense_form.html は移動経路・宿泊費・日当の3 FormSetの金額を合算
- バーの高さ分、フォーム下部に padding を確保しコンテンツが隠れないようにする
- 必須項目のラベルに赤い「＊」マークを追加（CSSで `label.required::after` を定義し、`data-required` / `data-approver-required` が付くフィールドおよびフォーム定義上requiredのフィールドに適用）

## タスク5: 新規申請ランチャー画面

対象: 新規テンプレート `expenses/templates/expenses/expense_type_launcher.html`、`expenses/views.py`、`expenses/urls.py`、`home.html`、`base.html`

- `/new/select/` のようなURLで、申請可能な全 M_DocumentType（category='expense'のグループ所属分）をカードで一覧表示する画面を追加
- カード構成: グループアイコン（base.htmlのmenu_group別FAアイコンと同じ）＋ 申請種別名 ＋ グループ名。クリックで `expense_create_by_type` へ遷移
- M_DocumentGroup.menu_order → DocType順で並べる
- home.html と expense_list.html の「新規申請」ボタンの遷移先をこの画面に変更
- 既存の `/new/`（DocType=1直行）は互換のため残す
- デザインは settlement_menu.html のカードグリッド（card-hover-primary）を踏襲

## タスク6: Bootswatch sandstoneの廃止

対象: `expenses/templates/expenses/base.html` 9行目

- `bootswatch@5.3.3/dist/sandstone/bootstrap.min.css` を素の `bootstrap@5.3.3/dist/css/bootstrap.min.css`（jsdelivr）に差し替え
- 差し替え後、swiss.cssのスコープ外（モーダル等 `.precision-main` の外側）の見た目が崩れないか、主要画面のボタン・フォーム・モーダルを確認
- 崩れる箇所があれば swiss.css に最小限の補正を追加（例: モーダル内ボタンのスタイル）

## タスク7: ダッシュボードKPIサマリー＋行クリック

対象: `expenses/templates/expenses/home.html`、`expenses/views.py`（homeビュー）、`swiss.css`

- 3つのテーブルの上にKPIカードを横並びで追加: 「承認待ち N件」（承認者ロールのみ）／「申請中 N件」／「下書き N件」。各カードはクリックで対応一覧へ遷移
- 件数はhomeビューで既に取得しているquerysetのcountを利用（追加クエリは最小限に）
- 各テーブルの行に expense_list.html と同じ `table-row-link` ＋ data-href ＋ クリックJSを追加（既存の「詳細」「編集」ボタンは残す）

## タスク8: 表示の統一・CSS整理

対象: 複数テンプレート、`swiss.css`

1. home.html 下書きテーブルの `badge bg-secondary` を `status-pill status-pill-draft` に統一（status_badge_classフィルタの利用を検討）
2. 紺色カードヘッダーのインラインstyle `style="background:#17307a; border-radius:8px 8px 0 0;"` を swiss.css の新クラス `.card-header-navy`（背景 `var(--primary)`・白文字・アイコン白）に置換。対象は grep で `background:#17307a` を全テンプレートから検索して全箇所
3. approval_detail.html の `<style>` 内 `.detail-item-card` 系定義は swiss.css と重複しているので削除（差分がある場合はswiss.css側に統合）
4. settlement_menu.html の赤バッジのインラインstyle（`background:#dc3545`）を `.sidebar-badge` 相当の共通クラスに置換

## タスク9: 仕上げ（小粒・まとめて1コミットで可）

1. expense_list.html の下書き削除 `window.confirm` を expense_form.html と同様のBootstrap確認モーダルに統一
2. 一覧のフィルタ適用中、フィルタカードの下に条件チップを表示（例: 「ステータス: 申請中 ×」、×クリックでその条件のみ解除して再検索）。対象: expense_list.html / approval_list.html
3. login.html にパスワード表示/非表示トグル（目アイコン）を追加
4. 行クリックテーブル（table-row-link）のキーボード対応: tr に `tabindex="0"` とEnterキーでの遷移を追加

## 共通の注意

- 既存のクラス命名規則（precision-*, status-pill-*, カラートークン var(--primary) 等）に従う
- インラインstyleの新規追加は避け、swiss.cssにクラスを追加する
- JSはbase.htmlの既存パターン（IIFE、`window.xxx` 公開、`_bound`フラグによる二重バインド防止）に合わせる
- 各タスク完了ごとにgitコミット（日本語コミットメッセージ）
- `python manage.py test` は実行しない（CLAUDE.md参照）
