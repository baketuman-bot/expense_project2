# 固定資産(assets)スコープの承認者自動割当 — 設計

## 背景・目的

承認ステップ (`M_WorkflowStep.allowed_bumon_scope`) に `keiri`（経理）をセットすると、申請者は承認者を選択せず、`M_UserRole.role='keiri'` を持つ全ユーザーが自動的に承認待ち（OR承認）として登録される。

固定資産関連の申請でも同様の仕組みが必要で、`allowed_bumon_scope='assets'` をセットしたステップでは `M_UserRole.role='assets'` を持つユーザーが自動割当され、申請者の選択を不要にする。

候補者抽出ロジック自体（`utils.candidates_for_step` の else分岐: `roles__role=scope` フィルタ）は既に scope の値を問わず汎用的に動作するため、`assets` でも候補者は取得できる。問題は「自動割当・選択不要化（OR承認登録）」の挙動が複数箇所で `scope == 'keiri'` という文字列リテラルにハードコードされている点。

## スコープ外

- `keiri_approval_edit`（経理承認者によるデータ修正機能、views.py:1560-1888）は別機能であり、本対応では `assets` に拡張しない。
- `M_WorkflowStep.BUMON_SCOPE_CHOICES` に存在するが他の選択肢（`others` 等）の不整合修正は対象外。
- `M_UserRole.role='assets'` の付与自体は既存のDjango Admin（UserRoleInline）で可能なため、追加実装不要。

## 変更内容

### 1. models.py + マイグレーション

`M_WorkflowStep.BUMON_SCOPE_CHOICES` に `('assets', '固定資産')` を追加。これがないと `/settings/master/m_workflow_step/` の編集フォームで `assets` を選択できない。

非破壊的な `AlterField` マイグレーション（0056）を追加。

### 2. utils.py

```python
OR_APPROVAL_SCOPES = {'keiri', 'assets'}
OR_APPROVAL_SCOPE_LABELS = {'keiri': '経理部門', 'assets': '固定資産担当'}
OR_APPROVAL_SCOPE_SHORT_LABELS = {'keiri': '経理', 'assets': '資産'}
```

- `steps_with_candidates()`: 各ステップ辞書に `'is_or_approval': scope_norm in OR_APPROVAL_SCOPES` を追加。views.py / テンプレートはこのフラグを参照することで `'keiri'` 文字列への直接依存をなくす。
- `get_pending_approvers()`: `allowed_bumon_scope='keiri'` の絞り込みを `allowed_bumon_scope__in=OR_APPROVAL_SCOPES` に一般化。集約表示名はステップごとに `OR_APPROVAL_SCOPE_LABELS` から取得する（経理="経理部門"、固定資産="固定資産担当"）。

### 3. views.py

- import に `OR_APPROVAL_SCOPES`, `OR_APPROVAL_SCOPE_LABELS` を追加。
- 以下 6 箇所の `s.get('allowed_bumon_scope') == 'keiri'` を `s.get('is_or_approval')` に置換:
  - 承認者必須チェック（編集時 / 新規作成時）×2
  - 申請確定時の承認者OR登録（候補者全員を pending 登録）
  - 再申請時の承認者更新（スキップ判定）
  - 下書き保存時の仮承認者登録
- `_build_approval_flow()`: `allowed_bumon_scope='keiri'` フィルタを `__in=OR_APPROVAL_SCOPES` に一般化し、集約ラベルを `[経理]` / `[資産]` のようにスコープごとに出し分ける。
- 承認一覧の `pending_approver_map` 生成箇所も同様に一般化。

### 4. テンプレート (expense_form.html / travel_expense_form.html)

`{% if s.allowed_bumon_scope == 'keiri' %}` を `{% if s.is_or_approval %}` に変更し、案内文を「このステップは自動で回付されます（選択不要）。」に汎用化する。

## テスト方針

`expenses/tests.py` の既存スタイル（Django `TestCase`、モック併用）に倣い、以下を確認するテストを追加する:

- `candidates_for_step` が `allowed_bumon_scope='assets'` のステップに対し `M_UserRole.role='assets'` のユーザーのみを返すこと
- `steps_with_candidates` が `assets` スコープのステップに `is_or_approval=True` を設定すること
- `get_pending_approvers` が `assets` ステップの複数候補者を「固定資産担当」1エントリに集約すること

テスト実行（`python manage.py test`）は本番DBに対して安全でない可能性があるため、実行前に `test_expense_db` への権限が付与されているかをユーザーに確認する。
