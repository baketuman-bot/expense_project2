# t_documentcontents settle_kbn 追加 + v_documentcontents 更新 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `t_documentcontents` に `settle_kbn char(10)` フィールドを追加し、`v_documentcontents` ビューに `d.pay_kbn` と `dc.settle_kbn` を追加する。

**Architecture:** Django モデルにフィールドを追加して `makemigrations` でマイグレーションを生成し、同マイグレーション内の `RunPython` で `v_documentcontents` ビューを再作成する。`view_sqls.py` の SQL 定義を更新することでマイグレーションと実行時の SQL を一致させる。

**Tech Stack:** Django 5.2, MySQL 8.0, Python 3.12

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `expenses/models.py` | 修正 | `T_DocumentContent` に `settle_kbn` フィールド追加 |
| `expenses/view_sqls.py` | 修正 | `_V_DOCUMENTCONTENTS` に `d.pay_kbn`, `dc.settle_kbn` 追加 |
| `expenses/migrations/0060_add_settle_kbn_to_documentcontents.py` | 新規 | `AddField` + `RunPython` でビュー再作成 |
| `expenses/tests.py` | 修正 | `SettleKbnFieldTest` クラス追加 |

---

## Task 1: テストを書く（失敗を確認）

**Files:**
- Modify: `expenses/tests.py`

### 背景

`expenses/tests.py` 末尾に `SettleKbnFieldTest` クラスを追加する。`from unittest.mock import patch` と `from django.test import TestCase` は既にファイル冒頭でインポート済み。

### Steps

- [ ] **Step 1: テストクラスを追加する**

`expenses/tests.py` 末尾に追記:

```python
class SettleKbnFieldTest(TestCase):
    """settle_kbn フィールド追加と v_documentcontents ビュー更新のテスト"""

    def test_model_has_settle_kbn_field(self):
        """T_DocumentContent モデルに settle_kbn フィールドが存在すること"""
        from expenses.models import T_DocumentContent
        field = T_DocumentContent._meta.get_field('settle_kbn')
        self.assertEqual(field.max_length, 10)
        self.assertTrue(field.null)
        self.assertTrue(field.blank)

    def test_settle_kbn_can_be_saved_and_retrieved(self):
        """settle_kbn に値をセットして保存・取得できること"""
        from expenses.models import (
            T_DocumentContent, T_Document, M_DocumentType, M_User, M_Status
        )
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # 最小限のフィクスチャを作成
        status = M_Status.objects.create(status_cd='DRA', status_name='下書き')
        doc_type = M_DocumentType.objects.filter(document_type_id=1).first()
        if doc_type is None:
            doc_type = M_DocumentType.objects.create(
                document_type_id=1,
                document_type_name='テスト種別',
            )
        user = User.objects.create_user(
            username='settle_test_user',
            man_number='STL001',
            user_name='テストユーザー',
            password='pass123',
        )
        doc = T_Document.objects.create(
            document_type=doc_type,
            title='テスト申請',
            man_number=user,
            status_cd=status,
        )
        content = T_DocumentContent.objects.create(
            document=doc,
            settle_kbn='01',
        )
        retrieved = T_DocumentContent.objects.get(pk=content.pk)
        self.assertEqual(retrieved.settle_kbn, '01')

    def test_view_sql_contains_pay_kbn(self):
        """`_V_DOCUMENTCONTENTS` SQL に d.pay_kbn が含まれること"""
        from expenses.view_sqls import _V_DOCUMENTCONTENTS
        self.assertIn('d.pay_kbn', _V_DOCUMENTCONTENTS)

    def test_view_sql_contains_settle_kbn(self):
        """`_V_DOCUMENTCONTENTS` SQL に dc.settle_kbn が含まれること"""
        from expenses.view_sqls import _V_DOCUMENTCONTENTS
        self.assertIn('dc.settle_kbn', _V_DOCUMENTCONTENTS)
```

> **注意:** `_V_DOCUMENTCONTENTS` は `view_sqls.py` のモジュールレベル変数。`from expenses.view_sqls import _V_DOCUMENTCONTENTS` でインポートできる（`_` 付きだが Python からは通常通りインポート可能）。

- [ ] **Step 2: テストを実行して失敗を確認する**

```bash
wsl -d Ubuntu-24.04 bash -c "cd /home/idc_user/expense_project2 && python manage.py test expenses.tests.SettleKbnFieldTest --keepdb 2>&1 | tail -20"
```

Expected: `FAIL` または `ERROR` — `settle_kbn` フィールドが存在しないため失敗する。`test_view_sql_*` も `pay_kbn`/`settle_kbn` が SQL にないため失敗する。

- [ ] **Step 3: コミット**

```bash
wsl -d Ubuntu-24.04 bash -c "cd /home/idc_user/expense_project2 && git add expenses/tests.py && git commit -m 'test: settle_kbn フィールドと v_documentcontents の失敗テストを追加'"
```

---

## Task 2: モデル・ビューSQL・マイグレーションの実装

**Files:**
- Modify: `expenses/models.py` (`T_DocumentContent` クラス、約 600-628 行目)
- Modify: `expenses/view_sqls.py` (`_V_DOCUMENTCONTENTS`、148-172 行目)
- Create: `expenses/migrations/0060_add_settle_kbn_to_documentcontents.py`

### 背景

`T_DocumentContent` クラスは `expenses/models.py` の 600 行目付近。フィールドは `corpo_card_no` (約 625 行目) で終わっている。その直後に `settle_kbn` を追加する。

`view_sqls.py` の `_V_DOCUMENTCONTENTS` は 148-172 行目。`d.pay_kbn` と `dc.settle_kbn` を SELECT リストに追加する。

マイグレーションは最新 (0059) 以降の 0060 番。`makemigrations` で自動生成後、`RunPython` を手動追記する。

### Steps

- [ ] **Step 1: `T_DocumentContent` に `settle_kbn` フィールドを追加する**

`expenses/models.py` の `T_DocumentContent` クラス内、`corpo_card_no` フィールド定義の直後に追記:

```python
    settle_kbn = models.CharField("精算区分", max_length=10, null=True, blank=True, db_column='settle_kbn')
```

追加後の `T_DocumentContent` のフィールド末尾部分:
```python
    corpo_card = models.IntegerField("コーポレートカード支払い", null=True, blank=True)
    corpo_card_no = models.CharField("カード番号", max_length=10, null=True, blank=True)
    settle_kbn = models.CharField("精算区分", max_length=10, null=True, blank=True, db_column='settle_kbn')
```

- [ ] **Step 2: `_V_DOCUMENTCONTENTS` SQL を更新する**

`expenses/view_sqls.py` の `_V_DOCUMENTCONTENTS` を以下に置き換える:

```python
_V_DOCUMENTCONTENTS = """
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
"""
```

- [ ] **Step 3: マイグレーションを自動生成する**

```bash
wsl -d Ubuntu-24.04 bash -c "cd /home/idc_user/expense_project2 && python manage.py makemigrations expenses --name add_settle_kbn_to_documentcontents 2>&1"
```

Expected: `expenses/migrations/0060_add_settle_kbn_to_documentcontents.py` が生成される。

- [ ] **Step 4: マイグレーションファイルに `RunPython` を追記する**

生成された `expenses/migrations/0060_add_settle_kbn_to_documentcontents.py` を開き、`operations` リストの `AddField` の後に以下を追加する:

まず `import warnings` と `from expenses.view_sqls import ALL_VIEWS` をファイル冒頭のインポート部に追加:

```python
import warnings
from django.db import migrations, models
from expenses.view_sqls import ALL_VIEWS
```

次に `operations` リストを以下のように変更する（`AddField` の後に `RunPython` を追加）:

```python
def recreate_v_documentcontents(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        try:
            cur.execute(ALL_VIEWS['v_documentcontents'])
        except Exception as e:
            warnings.warn(f"[0060] v_documentcontents VIEW の再作成をスキップ ({e})")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0059_remove_role_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='t_documentcontent',
            name='settle_kbn',
            field=models.CharField(blank=True, db_column='settle_kbn', max_length=10, null=True, verbose_name='精算区分'),
        ),
        migrations.RunPython(recreate_v_documentcontents, reverse_code=noop),
    ]
```

> **注意:** `makemigrations` が生成した `AddField` の内容をそのまま使う。上記は参考例。実際に生成されたファイルの `AddField` 部分を保持し、その後に `RunPython` を追加すること。

- [ ] **Step 5: マイグレーションを適用する**

```bash
wsl -d Ubuntu-24.04 bash -c "cd /home/idc_user/expense_project2 && python manage.py migrate expenses 2>&1 | tail -10"
```

Expected: `Applying expenses.0060_add_settle_kbn_to_documentcontents... OK`

- [ ] **Step 6: テストを実行してパスを確認する**

```bash
wsl -d Ubuntu-24.04 bash -c "cd /home/idc_user/expense_project2 && python manage.py test expenses.tests.SettleKbnFieldTest --keepdb 2>&1 | tail -10"
```

Expected: `OK (4 tests)`

- [ ] **Step 7: Django system check を実行する**

```bash
wsl -d Ubuntu-24.04 bash -c "cd /home/idc_user/expense_project2 && python manage.py check 2>&1"
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 8: コミット**

```bash
wsl -d Ubuntu-24.04 bash -c "cd /home/idc_user/expense_project2 && git add expenses/models.py expenses/view_sqls.py expenses/migrations/0060_add_settle_kbn_to_documentcontents.py && git commit -m 'feat: t_documentcontents に settle_kbn を追加し v_documentcontents を更新'"
```

---

## 完了チェック

- [ ] `python manage.py test expenses.tests.SettleKbnFieldTest --keepdb` が 4 件パス
- [ ] `python manage.py test expenses --keepdb` で既存テストが壊れていないこと
- [ ] `python manage.py migrate` が正常完了
- [ ] MySQL で `DESCRIBE t_documentcontents` に `settle_kbn` が存在すること
- [ ] MySQL で `SHOW CREATE VIEW v_documentcontents` に `pay_kbn` と `settle_kbn` が含まれること
