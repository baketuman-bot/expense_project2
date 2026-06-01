# 設計ドキュメント: t_documentcontents settle_kbn 追加 + v_documentcontents 更新

**日付:** 2026-06-01

---

## 概要

`t_documentcontents` テーブルに `settle_kbn` フィールドを追加し、`v_documentcontents` ビューに `pay_kbn`（t_documents）と `settle_kbn`（t_documentcontents）を追加する。

---

## 変更内容

### 1. T_DocumentContent モデル (`expenses/models.py`)

`T_DocumentContent` クラスに以下のフィールドを追加:

```python
settle_kbn = models.CharField("精算区分", max_length=10, null=True, blank=True, db_column='settle_kbn')
```

### 2. Django マイグレーション

- `makemigrations` で `settle_kbn` フィールドの追加マイグレーションを生成
- 同じマイグレーション内（または連続するマイグレーション）で `v_documentcontents` ビューを `RunSQL` で再作成

### 3. `view_sqls.py` の `_V_DOCUMENTCONTENTS` 更新

現在の SELECT に以下の2フィールドを追加:

```sql
d.pay_kbn,
dc.settle_kbn
```

更新後の SQL（抜粋）:

```sql
CREATE OR REPLACE VIEW v_documentcontents AS
SELECT
  dc.document_detail_id,
  dc.document_id,
  d.title           AS document_title,
  d.document_type_id,
  dt.document_type_name,
  g.menu_group_name,
  g.category,
  dc.date,
  dc.account_id     AS account_cd,
  a.account_name,
  dc.tekikaku_cd,
  dc.shiharaisaki,
  dc.purpose,
  dc.amount,
  dc.corpo_card,
  dc.corpo_card_no,
  d.pay_kbn,
  dc.settle_kbn
FROM t_documentcontents dc
LEFT JOIN t_documents      d  ON d.document_id       = dc.document_id
LEFT JOIN m_document_types dt ON dt.document_type_id = d.document_type_id
LEFT JOIN m_document_group g  ON g.menu_group        = dt.menu_group
LEFT JOIN m_account        a  ON a.account_cd        = dc.account_id
```

### 4. マイグレーション内での RunSQL

```python
from expenses.view_sqls import ALL_VIEWS

operations = [
    migrations.AddField(...),  # settle_kbn フィールド追加
    migrations.RunSQL(
        sql=ALL_VIEWS['v_documentcontents'],
        reverse_sql="DROP VIEW IF EXISTS v_documentcontents",
    ),
]
```

---

## ファイル変更一覧

| ファイル | 変更内容 |
|---|---|
| `expenses/models.py` | `T_DocumentContent` に `settle_kbn` フィールド追加 |
| `expenses/view_sqls.py` | `_V_DOCUMENTCONTENTS` に `d.pay_kbn`, `dc.settle_kbn` 追加 |
| `expenses/migrations/XXXX_add_settle_kbn.py` | `AddField` + `RunSQL` (ビュー再作成) |

---

## 注意事項

- `migrate` 実行時にビューが自動的に再作成される
- `view_sqls.py` の変更と migration の `RunSQL` は同一内容であること（ドリフト防止）
- `settle_kbn` は `null=True, blank=True` のため既存レコードへの影響なし
