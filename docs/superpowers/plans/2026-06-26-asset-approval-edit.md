# 固定資産申請の承認画面データ修正機能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `keiri` / `assets` / `admin` ロールを持つユーザーが固定資産申請の承認画面からデータを修正できるようにする。

**Architecture:** `_can_do_keiri_edit()` 関数に固定資産申請（`category='assets'`）向けの分岐を追加し、`approval_detail` ビューの `can_keiri_edit` 計算を `_is_keiri_approver()` から `_can_do_keiri_edit()` に統一する。テンプレート・URL は変更不要。

**Tech Stack:** Django 5.2 / Python 3.12 / MySQL 8.0（ローカル開発）

## Global Constraints

- 本番 DB（`expense_db`）への破壊的操作禁止（DELETE / TRUNCATE / DROP）
- `python manage.py test` には `DJANGO_TEST_DB_NAME=expense_db` を使用しない
- モデル命名規則: マスタ `M_`、トランザクション `T_`
- ロール定義は `M_UserRole.role` 文字列で管理（`'assets'`, `'keiri'`, `'admin'`, `'approver'`）
- 固定資産判定は `_is_asset_doc_type(doc_type)` を使用（`menu_group.category == 'assets'`）

---

## File Map

| ファイル | 変更種別 | 変更内容 |
|----------|----------|----------|
| `expenses/views.py` | **修正** | `_can_do_keiri_edit()` に固定資産分岐追加 / `approval_detail` ビューで `_can_do_keiri_edit()` を使用 |
| `expenses/tests.py` | **修正** | `_can_do_keiri_edit()` のユニットテスト追加（モック使用） |

---

## Task 1: `_can_do_keiri_edit()` に固定資産対応を追加してテスト

**Files:**
- Modify: `expenses/views.py:1612-1627`（`_can_do_keiri_edit` 関数全体）
- Test: `expenses/tests.py`（末尾に追記）

**Interfaces:**
- Produces: `_can_do_keiri_edit(user, document) -> bool`
  - 固定資産申請かつ `assets` スコープのステップ承認中 → `assets/keiri/admin` ロールで `True`
  - 固定資産申請かつ `FNS` → `assets/keiri/admin` ロールで `True`
  - 非固定資産の既存ロジックは変更なし

- [ ] **Step 1: 既存テストを実行して現状を確認**

```bash
python manage.py test expenses.tests.SiteUrlSettingsTest -v 2
```

期待: すべて PASS（既存テストが壊れていないことを確認）

- [ ] **Step 2: 固定資産申請用のテストを `expenses/tests.py` に追記**

`expenses/tests.py` のファイル末尾（最終行の後）に追記：

```python
from unittest.mock import MagicMock, patch, PropertyMock


class CanDoKeiriEditAssetTest(TestCase):
    """_can_do_keiri_edit: 固定資産申請における権限チェックのテスト（モック使用）"""

    def _make_doc(self, is_asset=True, status_cd='INPRO'):
        doc = MagicMock()
        mg = MagicMock()
        mg.category = 'assets' if is_asset else 'expense'
        mg.menu_group = 'AST' if is_asset else 'PAY'
        dt = MagicMock()
        dt.menu_group = mg
        doc.document_type = dt
        status = MagicMock()
        status.status_cd = status_cd
        doc.status_cd = status
        return doc

    def _make_user(self, roles):
        user = MagicMock()
        user.man_number = 'test001'
        return user

    @patch('expenses.views.T_WorkflowInstance')
    @patch('expenses.views.M_UserRole')
    @patch('expenses.views._is_asset_doc_type')
    def test_asset_doc_assets_scope_with_assets_role_returns_true(
        self, mock_is_asset, mock_role, mock_twi
    ):
        """固定資産申請 + assets スコープ承認中 + assets ロール → True"""
        from expenses.views import _can_do_keiri_edit
        mock_is_asset.return_value = True

        inst = MagicMock()
        inst.step.allowed_bumon_scope = 'assets'
        mock_twi.objects.filter.return_value.order_by.return_value.first.return_value = inst
        mock_role.objects.filter.return_value.exists.return_value = True

        user = self._make_user(['assets'])
        doc = self._make_doc(is_asset=True, status_cd='INPRO')

        result = _can_do_keiri_edit(user, doc)
        self.assertTrue(result)

    @patch('expenses.views.T_WorkflowInstance')
    @patch('expenses.views.M_UserRole')
    @patch('expenses.views._is_asset_doc_type')
    def test_asset_doc_fns_with_keiri_role_returns_true(
        self, mock_is_asset, mock_role, mock_twi
    ):
        """固定資産申請 + FNS + keiri ロール → True"""
        from expenses.views import _can_do_keiri_edit
        mock_is_asset.return_value = True

        inst = MagicMock()
        inst.step.allowed_bumon_scope = 'keiri'  # assets スコープでないステップ
        mock_twi.objects.filter.return_value.order_by.return_value.first.return_value = inst
        mock_role.objects.filter.return_value.exists.return_value = True

        user = self._make_user(['keiri'])
        doc = self._make_doc(is_asset=True, status_cd='FNS')

        result = _can_do_keiri_edit(user, doc)
        self.assertTrue(result)

    @patch('expenses.views.T_WorkflowInstance')
    @patch('expenses.views.M_UserRole')
    @patch('expenses.views._is_asset_doc_type')
    def test_asset_doc_without_role_returns_false(
        self, mock_is_asset, mock_role, mock_twi
    ):
        """固定資産申請 + assets スコープ + ロールなし → False"""
        from expenses.views import _can_do_keiri_edit
        mock_is_asset.return_value = True

        inst = MagicMock()
        inst.step.allowed_bumon_scope = 'assets'
        mock_twi.objects.filter.return_value.order_by.return_value.first.return_value = inst
        mock_role.objects.filter.return_value.exists.return_value = False

        user = self._make_user([])
        doc = self._make_doc(is_asset=True, status_cd='INPRO')

        result = _can_do_keiri_edit(user, doc)
        self.assertFalse(result)

    @patch('expenses.views.T_WorkflowInstance')
    @patch('expenses.views.M_UserRole')
    @patch('expenses.views._is_asset_doc_type')
    @patch('expenses.views._is_keiri_approver')
    def test_non_asset_doc_falls_through_to_keiri_logic(
        self, mock_is_keiri_approver, mock_is_asset, mock_role, mock_twi
    ):
        """非固定資産申請 → 既存の keiri ロジックに委譲"""
        from expenses.views import _can_do_keiri_edit
        mock_is_asset.return_value = False
        mock_is_keiri_approver.return_value = True

        user = self._make_user(['keiri'])
        doc = self._make_doc(is_asset=False, status_cd='INPRO')

        result = _can_do_keiri_edit(user, doc)
        self.assertTrue(result)
        mock_is_keiri_approver.assert_called_once_with(user, doc)
```

- [ ] **Step 3: テストを実行して失敗することを確認**

```bash
python manage.py test expenses.tests.CanDoKeiriEditAssetTest -v 2
```

期待: `test_asset_doc_assets_scope_with_assets_role_returns_true` が FAIL（固定資産分岐がまだない）

- [ ] **Step 4: `_can_do_keiri_edit()` を修正**

`expenses/views.py` の `_can_do_keiri_edit` 関数（約1612〜1627行）を以下に置き換え：

```python
def _can_do_keiri_edit(user, document):
    """承認者によるデータ修正権限チェック。keiri（経費）と assets（固定資産）に対応。"""
    is_asset = _is_asset_doc_type(getattr(document, 'document_type', None))

    if is_asset:
        asset_roles = ['assets', 'keiri', 'admin']
        try:
            inst = T_WorkflowInstance.objects.filter(document_id=document).order_by('-started_at').first()
            if inst and inst.step and inst.step.allowed_bumon_scope == 'assets':
                if M_UserRole.objects.filter(man_number=user, role__in=asset_roles).exists():
                    return True
        except Exception:
            pass
        try:
            status_cd = getattr(getattr(document, 'status_cd', None), 'status_cd', None)
            if status_cd == 'FNS':
                return M_UserRole.objects.filter(man_number=user, role__in=asset_roles).exists()
        except Exception:
            pass
        return False
    else:
        if _is_keiri_approver(user, document):
            return True
        try:
            status_cd = getattr(getattr(document, 'status_cd', None), 'status_cd', None)
            if status_cd == 'FNS':
                return M_UserRole.objects.filter(
                    man_number=user, role__in=['keiri', 'approver'],
                ).exists()
        except Exception:
            pass
        return False
```

- [ ] **Step 5: テストを再実行して全件 PASS を確認**

```bash
python manage.py test expenses.tests.CanDoKeiriEditAssetTest -v 2
```

期待: 4件すべて PASS

- [ ] **Step 6: 既存テストも通ることを確認**

```bash
python manage.py test expenses -v 2
```

期待: 全件 PASS

- [ ] **Step 7: コミット**

```bash
git add expenses/views.py expenses/tests.py
git commit -m "feat: _can_do_keiri_edit に固定資産申請（assets/keiri/admin ロール）対応を追加"
```

---

## Task 2: `approval_detail` ビューの `can_keiri_edit` 計算を統一

**Files:**
- Modify: `expenses/views.py:3444`（`approval_detail` ビュー内の1行）

**Interfaces:**
- Consumes: Task 1 の `_can_do_keiri_edit(user, document) -> bool`

- [ ] **Step 1: 対象行を確認**

`expenses/views.py` の約3444行目を確認：

```python
can_keiri_edit = _is_keiri_approver(request.user, expense)
```

- [ ] **Step 2: 1行を修正**

上記の行を以下に変更：

```python
can_keiri_edit = _can_do_keiri_edit(request.user, expense)
```

- [ ] **Step 3: テストを実行**

```bash
python manage.py test expenses -v 2
```

期待: 全件 PASS

- [ ] **Step 4: 開発サーバーで動作確認**

```bash
python manage.py runserver
```

確認項目：
1. `assets` ロールを持つユーザーで固定資産申請の承認画面（`/approvals/<id>/`）を開く
2. ページ右上に「データ修正」ボタンが表示されること
3. 「データ修正」ボタンをクリックすると `keiri_approval_edit` 画面に遷移し、固定資産フォームが正しく表示されること（通貨・精算方法が非表示）
4. `assets` ロールを**持たない**一般ユーザーでは「データ修正」ボタンが表示されないこと
5. FNS（最終承認済み）状態の固定資産申請でも `assets` ロールがあればボタンが表示されること

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py
git commit -m "fix: approval_detail の can_keiri_edit を _can_do_keiri_edit に統一（FNS後・固定資産対応）"
```
