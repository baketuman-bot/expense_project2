# 固定資産申請の承認画面データ修正機能 — 設計ドキュメント

**日付:** 2026-06-26  
**対象:** `expenses/views.py`

---

## 背景・目的

固定資産関連の申請書（AST グループ、`menu_group.category == 'assets'`）において、`keiri` / `assets` / `admin` ロールを持つユーザーが承認画面からデータを修正できるようにする。

現状、経費申請（PAY / REC / TRV 等）では `keiri` / `approver` ロールが `keiri_approval_edit` ビューからデータ修正できるが、固定資産申請ではワークフローのステップスコープが `assets` になるため、修正ボタンが表示されない。

---

## 現状の問題点

### 関数の不一致

| 箇所 | 使用関数 | 挙動 |
|------|----------|------|
| `expense_detail` ビュー | `_can_do_keiri_edit()` | keiri スコープ中 or FNS 後も許可 |
| `approval_detail` ビュー | `_is_keiri_approver()` | keiri スコープのステップ中**のみ** |
| `settings_approval_detail` ビュー | 未対応 | ボタンなし |

`approval_detail` が `_is_keiri_approver()` を使っているため、FNS 後は修正ボタンが消えるという既存の不一致も存在する。

### 固定資産申請が対象外になる理由

`_is_keiri_approver()` / `_can_do_keiri_edit()` はいずれも `allowed_bumon_scope == 'keiri'` のステップのみを対象としており、固定資産申請が使う `allowed_bumon_scope == 'assets'` のステップは判定外。

---

## 設計（アプローチ A）

### 変更方針

最小変更・最大効果。`views.py` の2箇所のみ変更。

### 変更 1: `_can_do_keiri_edit()` に固定資産分岐を追加

```python
def _can_do_keiri_edit(user, document):
    is_asset = _is_asset_doc_type(getattr(document, 'document_type', None))

    if is_asset:
        # 固定資産申請: assets/keiri/admin ロール + 承認中(assets スコープ)または FNS 後
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
        # 既存の経費申請ロジック（変更なし）
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

### 変更 2: `approval_detail` ビューの `can_keiri_edit` 計算を統一

```python
# 変更前
can_keiri_edit = _is_keiri_approver(request.user, expense)

# 変更後
can_keiri_edit = _can_do_keiri_edit(request.user, expense)
```

### 変更不要な箇所

- `keiri_approval_edit` ビュー: すでに `_can_do_keiri_edit()` でゲート済み、`_asset_form_context()` 適用済み
- `approval_detail.html` テンプレート: `can_keiri_edit` フラグをそのまま参照している
- `expense_detail` ビュー: すでに `_can_do_keiri_edit()` を使用済み

---

## 権限マトリクス

| 申請種別 | ロール | 承認中（assets/keiri スコープ） | FNS 後 |
|----------|--------|----------------------------------|--------|
| 固定資産 | assets | ✓ | ✓ |
| 固定資産 | keiri | ✓ | ✓ |
| 固定資産 | admin | ✓ | ✓ |
| 経費 | keiri | ✓ | ✓ |
| 経費 | approver | ✓ | ✓ |

---

## 副次効果

`approval_detail` ビューで `_is_keiri_approver()` → `_can_do_keiri_edit()` に変更することで、既存の経費申請においても FNS 後の修正ボタン表示が `expense_detail` と一致するようになる（既存バグの修正）。

---

## スコープ外

- `settings_approval_detail`（管理者承認詳細）への修正ボタン追加は本件に含めない
- 修正履歴（`T_DocumentEditHistory`）の記録は既存実装で対応済み
