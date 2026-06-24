# 固定資産(assets)承認スコープ自動割当 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `M_WorkflowStep.allowed_bumon_scope='assets'` のステップで、`M_UserRole.role='assets'` のユーザーを `keiri`（経理）と同様に自動割当し、申請者が承認者を選択しなくてよいようにする。

**Architecture:** `keiri` スコープの自動割当（OR承認: 候補者全員を pending 登録し、誰か1人が承認すれば次へ進む）は現在 `scope == 'keiri'` という文字列リテラルで複数箇所にハードコードされている。これを `utils.py` の `OR_APPROVAL_SCOPES = {'keiri', 'assets'}` という集合と、`steps_with_candidates()` が返すステップ辞書に追加する `is_or_approval` フラグに一般化し、views.py / テンプレートはこのフラグを参照するように変更する。候補者抽出自体（`candidates_for_step` の `roles__role=scope` フィルタ）は既に scope の値を問わず汎用的に動作するため変更不要。

**Tech Stack:** Django 5.2.6 / Python 3.12 / MySQL（ローカル開発・テストとも `expense_db` 系を使用、テストは `test_expense_db` を使用）

## Global Constraints

- 本番DB (`expense_db`) を破壊的操作で変更しない。マイグレーションは `AlterField`（choices のみ変更、DBスキーマへの実害なし）に限定する。
- `python manage.py test` は `DJANGO_TEST_DB_NAME` を明示的に `expense_db` に設定しない限り `test_expense_db` を使うため安全（`expense_project/settings.py:111-132` で保証されている）。各タスクのテスト実行前に、現在のシェル環境に `DJANGO_TEST_DB_NAME=expense_db` がセットされていないことを確認する。
- `keiri_approval_edit`（経理承認者によるデータ修正機能、views.py:1560-1888）は本計画の対象外。`assets` スコープに拡張しない。
- 既存の `keiri` の挙動・表示文言を変更しない（回帰防止）。各テストで `keiri` 側の挙動も合わせて確認する。

---

### Task 1: `M_WorkflowStep.BUMON_SCOPE_CHOICES` に `assets` を追加

**Files:**
- Modify: `expenses/models.py`（`M_WorkflowStep.BUMON_SCOPE_CHOICES`、336行目付近）
- Create: `expenses/migrations/0076_add_assets_workflow_scope.py`
- Test: `expenses/tests.py`

**Note:** CLAUDE.md は「最新: 0055」と記載しているが、実際の最新マイグレーションは `0075_add_fields_to_item_and_bumon.py`（2026-06-24時点でWSL上で確認済み）。ドキュメントが古いだけで、依存関係は実際の最新ファイルを基準にすること。

**Interfaces:**
- Produces: `M_WorkflowStep.BUMON_SCOPE_CHOICES` に `('assets', '固定資産')` が含まれる（管理者設定画面 `/settings/master/m_workflow_step/` のドロップダウンに表示されるようになる）。

- [ ] **Step 1: Write the failing test**

`expenses/tests.py` の末尾に追加:

```python
class WorkflowStepAssetsScopeChoiceTest(TestCase):
    """M_WorkflowStep.BUMON_SCOPE_CHOICES に assets が追加されていることを確認する"""

    def test_assets_choice_exists(self):
        from expenses.models import M_WorkflowStep
        choices = dict(M_WorkflowStep.BUMON_SCOPE_CHOICES)
        self.assertEqual(choices.get('assets'), '固定資産')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test expenses.tests.WorkflowStepAssetsScopeChoiceTest -v 2`
Expected: FAIL（`choices.get('assets')` が `None` のため `assertEqual` が失敗）

- [ ] **Step 3: Modify models.py**

`expenses/models.py` 内、`class M_WorkflowStep` の `BUMON_SCOPE_CHOICES` を変更:

old:
```python
    BUMON_SCOPE_CHOICES = [
        ('same', '同一'),
        ('parent', '親'),
        ('keiri', '経理'),
        ('any', '全体'),
    ]
```

new:
```python
    BUMON_SCOPE_CHOICES = [
        ('same', '同一'),
        ('parent', '親'),
        ('keiri', '経理'),
        ('assets', '固定資産'),
        ('any', '全体'),
    ]
```

- [ ] **Step 4: Create the migration**

`makemigrations` が使えない場合（本番DB接続が必要なため）、以下の内容で手書きする。`expenses/migrations/0076_add_assets_workflow_scope.py`:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0075_add_fields_to_item_and_bumon'),
    ]

    operations = [
        migrations.AlterField(
            model_name='m_workflowstep',
            name='allowed_bumon_scope',
            field=models.CharField(
                choices=[
                    ('same', '同一'),
                    ('parent', '親'),
                    ('keiri', '経理'),
                    ('assets', '固定資産'),
                    ('any', '全体'),
                ],
                default='any',
                max_length=7,
                verbose_name='部門許可範囲',
            ),
        ),
    ]
```

可能であれば `python manage.py makemigrations expenses --check --dry-run` で内容が一致することを確認する（DB接続不要、モデル定義との整合性のみ確認）。

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test expenses.tests.WorkflowStepAssetsScopeChoiceTest -v 2`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add expenses/models.py expenses/migrations/0076_add_assets_workflow_scope.py expenses/tests.py
git commit -m "feat: M_WorkflowStepのallowed_bumon_scopeにassets選択肢を追加"
```

---

### Task 2: `utils.py` に `OR_APPROVAL_SCOPES` と `is_or_approval` フラグを追加

**Files:**
- Modify: `expenses/utils.py`
- Test: `expenses/tests.py`

**Interfaces:**
- Produces:
  - `utils.OR_APPROVAL_SCOPES`: `set[str]` = `{'keiri', 'assets'}`
  - `utils.OR_APPROVAL_SCOPE_LABELS`: `dict[str, str]` = `{'keiri': '経理部門', 'assets': '固定資産担当'}`
  - `utils.OR_APPROVAL_SCOPE_SHORT_LABELS`: `dict[str, str]` = `{'keiri': '経理', 'assets': '資産'}`
  - `steps_with_candidates()` が返す各ステップ辞書に `'is_or_approval': bool` キーが追加される
- Consumes: 既存の `candidates_for_step(applicant, step)`（変更なし）

- [ ] **Step 1: Write the failing tests**

`expenses/tests.py` の末尾に追加:

```python
class StepsWithCandidatesIsOrApprovalFlagTest(TestCase):
    """steps_with_candidates が is_or_approval フラグを正しく設定することを確認する"""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from expenses.models import M_WorkflowTemplate, M_Post
        User = get_user_model()
        self.applicant = User.objects.create_user(
            username='flag_applicant', man_number='FLAGAPP',
            user_name='申請者', password='pass123',
        )
        self.post = M_Post.objects.create(post_cd='FLAGPOST', post_name='部長', post_order=10)
        self.tpl = M_WorkflowTemplate.objects.create(workflow_template_name='フラグテスト')

    def _make_step(self, scope):
        from expenses.models import M_WorkflowStep
        return M_WorkflowStep.objects.create(
            workflow_template=self.tpl, step_order=1,
            allowed_bumon_scope=scope, approver_post=self.post,
        )

    def test_is_or_approval_true_for_assets_scope(self):
        from expenses.utils import steps_with_candidates
        self._make_step('assets')
        steps = steps_with_candidates(self.applicant, self.tpl)
        self.assertTrue(steps[0]['is_or_approval'])

    def test_is_or_approval_true_for_keiri_scope(self):
        from expenses.utils import steps_with_candidates
        self._make_step('keiri')
        steps = steps_with_candidates(self.applicant, self.tpl)
        self.assertTrue(steps[0]['is_or_approval'])

    def test_is_or_approval_false_for_any_scope(self):
        from expenses.utils import steps_with_candidates
        self._make_step('any')
        steps = steps_with_candidates(self.applicant, self.tpl)
        self.assertFalse(steps[0]['is_or_approval'])


class CandidatesForStepAssetsRoleTest(TestCase):
    """assets スコープでは M_UserRole.role='assets' のユーザーのみが候補になることを確認する"""

    def test_assets_scope_returns_only_assets_role_users(self):
        from django.contrib.auth import get_user_model
        from expenses.models import M_Post, M_WorkflowTemplate, M_WorkflowStep, M_UserRole
        from expenses.utils import candidates_for_step
        User = get_user_model()

        approver_post = M_Post.objects.create(post_cd='ASTPOST', post_name='担当', post_order=10)
        senior_post = M_Post.objects.create(post_cd='SENIORPOST', post_name='上位職', post_order=1)

        applicant = User.objects.create_user(
            username='ast_applicant', man_number='ASTAPP', user_name='申請者',
            password='pass123', post_cd=senior_post,
        )
        assets_user = User.objects.create_user(
            username='ast_user', man_number='ASTUSER', user_name='資産担当者',
            password='pass123', post_cd=senior_post,
        )
        M_UserRole.objects.create(man_number=assets_user, role='assets')
        other_user = User.objects.create_user(
            username='other_user', man_number='OTHERUSER', user_name='他部門ユーザー',
            password='pass123', post_cd=senior_post,
        )

        tpl = M_WorkflowTemplate.objects.create(workflow_template_name='資産候補テスト')
        step = M_WorkflowStep.objects.create(
            workflow_template=tpl, step_order=1,
            allowed_bumon_scope='assets', approver_post=approver_post,
        )

        candidates = list(candidates_for_step(applicant, step))
        self.assertIn(assets_user, candidates)
        self.assertNotIn(other_user, candidates)
        self.assertNotIn(applicant, candidates)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test expenses.tests.StepsWithCandidatesIsOrApprovalFlagTest expenses.tests.CandidatesForStepAssetsRoleTest -v 2`
Expected: `StepsWithCandidatesIsOrApprovalFlagTest` の3件は `KeyError: 'is_or_approval'` で FAIL。`CandidatesForStepAssetsRoleTest` は既存の `candidates_for_step` が scope を問わず `roles__role=scope` で絞り込むため、この時点でも PASS する可能性が高い（先に実行して確認する）。

- [ ] **Step 3: Modify utils.py — add constants**

`expenses/utils.py` の冒頭（import直後）に追加:

old:
```python
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Q, Subquery
from .models import M_User, M_BelongTo, V_Group, M_WorkflowStep

def _resolve_recipient(to_email: str | None):
```

new:
```python
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Q, Subquery
from .models import M_User, M_BelongTo, V_Group, M_WorkflowStep

# 自動割当（OR承認）対象スコープ: 申請者が選択せず、対応する M_UserRole.role を
# 持つユーザー全員が候補者として pending 登録される。
OR_APPROVAL_SCOPES = {'keiri', 'assets'}
OR_APPROVAL_SCOPE_LABELS = {
    'keiri': '経理部門',
    'assets': '固定資産担当',
}
OR_APPROVAL_SCOPE_SHORT_LABELS = {
    'keiri': '経理',
    'assets': '資産',
}

def _resolve_recipient(to_email: str | None):
```

- [ ] **Step 4: Modify utils.py — add `is_or_approval` to `steps_with_candidates()`**

old:
```python
        cands = candidates_for_step(applicant, s)
        scope_norm = str(s.allowed_bumon_scope or 'any').strip().lower()
        data.append({
            'step_id': s.pk,
            'step_order': s.step_order,
            'step_type': s.step_type,
            'allowed_bumon_scope': scope_norm,
            'approver_post_cd': s.approver_post.post_cd if s.approver_post else None,
```

new:
```python
        cands = candidates_for_step(applicant, s)
        scope_norm = str(s.allowed_bumon_scope or 'any').strip().lower()
        data.append({
            'step_id': s.pk,
            'step_order': s.step_order,
            'step_type': s.step_type,
            'allowed_bumon_scope': scope_norm,
            'is_or_approval': scope_norm in OR_APPROVAL_SCOPES,
            'approver_post_cd': s.approver_post.post_cd if s.approver_post else None,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test expenses.tests.StepsWithCandidatesIsOrApprovalFlagTest expenses.tests.CandidatesForStepAssetsRoleTest -v 2`
Expected: PASS（5 tests）

- [ ] **Step 6: Commit**

```bash
git add expenses/utils.py expenses/tests.py
git commit -m "feat: OR承認スコープ(keiri/assets)をutils.pyで一般化"
```

---

### Task 3: `get_pending_approvers()` を `assets` 対応に一般化

**Files:**
- Modify: `expenses/utils.py:138-213`（`get_pending_approvers` 関数全体）
- Test: `expenses/tests.py`

**Interfaces:**
- Consumes: `OR_APPROVAL_SCOPES`, `OR_APPROVAL_SCOPE_LABELS`（Task 2 で追加）
- Produces: `get_pending_approvers(document)` は `assets` スコープのステップで複数候補者がいる場合も `man_number.user_name == '固定資産担当'` の1エントリに集約する（`keiri` は従来通り `'経理部門'`）。

- [ ] **Step 1: Write the failing tests**

`expenses/tests.py` の末尾に追加:

```python
class OrApprovalAggregationFixtureMixin:
    """OR承認スコープ（keiri/assets）の集約テスト用フィクスチャ"""

    def _make_or_approval_fixture(self, scope):
        from django.contrib.auth import get_user_model
        from expenses.models import (
            M_WorkflowTemplate, M_WorkflowStep, M_DocumentType, M_Status,
            T_Document, T_DocumentApprover, M_UserRole,
        )
        User = get_user_model()

        applicant = User.objects.create_user(
            username=f'applicant_{scope}', man_number=f'APP_{scope.upper()}',
            user_name='申請者', password='pass123',
        )
        approvers = []
        for i in range(2):
            u = User.objects.create_user(
                username=f'{scope}_user_{i}', man_number=f'{scope.upper()}{i}',
                user_name=f'{scope}担当{i}', password='pass123',
            )
            M_UserRole.objects.create(man_number=u, role=scope)
            approvers.append(u)

        tpl = M_WorkflowTemplate.objects.create(workflow_template_name=f'テンプレ_{scope}')
        step = M_WorkflowStep.objects.create(
            workflow_template=tpl, step_order=1, allowed_bumon_scope=scope,
        )
        doc_type = M_DocumentType.objects.create(
            document_type_name=f'種別_{scope}', workflow_template_id=tpl,
        )
        status, _ = M_Status.objects.get_or_create(
            status_cd='DRA', defaults={'status_name': '下書き'}
        )
        doc = T_Document.objects.create(
            document_type=doc_type, title='テスト申請', man_number=applicant, status_cd=status,
        )
        for u in approvers:
            T_DocumentApprover.objects.create(
                document_id=doc, step_id=step, man_number=u, step_order=1, status='pending',
            )
        return doc, step


class GetPendingApproversAggregationTest(OrApprovalAggregationFixtureMixin, TestCase):
    """get_pending_approvers が OR承認スコープの複数候補者を1エントリに集約することを確認する"""

    def test_aggregates_assets_candidates_to_single_label(self):
        from expenses.utils import get_pending_approvers
        doc, _step = self._make_or_approval_fixture('assets')
        result = get_pending_approvers(doc)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].man_number.user_name, '固定資産担当')

    def test_aggregates_keiri_candidates_to_single_label(self):
        """回帰確認: keiri の既存挙動が変わっていないこと"""
        from expenses.utils import get_pending_approvers
        doc, _step = self._make_or_approval_fixture('keiri')
        result = get_pending_approvers(doc)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].man_number.user_name, '経理部門')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test expenses.tests.GetPendingApproversAggregationTest -v 2`
Expected: `test_aggregates_assets_candidates_to_single_label` は FAIL（`len(result) == 2`、個別ユーザー名のまま）。`test_aggregates_keiri_candidates_to_single_label` は現状の実装でも PASS するはずなので、先に実行して回帰確認のベースラインを取る。

- [ ] **Step 3: Replace `get_pending_approvers()` in utils.py**

`expenses/utils.py` の `get_pending_approvers` 関数全体を以下に置き換える:

old（関数全体、138〜213行目付近、`def get_pending_approvers(document):` から `return sorted(result, key=lambda x: x.step_order or 0)` まで）:
```python
def get_pending_approvers(document):
    """承認予定者（未処理）一覧を返す。

    T_DocumentApprover に登録済みの pending/draft 行を返す。
    keiri スコープのステップは複数候補者が登録されている場合でも
    「経理部門」として1エントリに集約して返す。

    テンプレートが参照する属性: step_order / man_number.user_name /
    man_number.post_cd.post_name
    """
    from types import SimpleNamespace
    from .models import T_DocumentApprover, T_WorkflowAction, M_WorkflowStep

    explicit = list(
        T_DocumentApprover.objects
        .filter(document_id=document, status__in=['pending', 'draft'])
        .select_related('man_number', 'man_number__post_cd', 'step_id')
    )

    doc_type = getattr(document, 'document_type', None)
    tpl = getattr(doc_type, 'workflow_template_id', None) if doc_type else None
    if not tpl:
        return sorted(explicit, key=lambda x: x.step_order or 0)

    keiri_steps = list(
        M_WorkflowStep.objects
        .filter(workflow_template=tpl, allowed_bumon_scope='keiri')
        .select_related('approver_post')
        .order_by('step_order')
    )
    keiri_step_ids = {s.step_id for s in keiri_steps}
    keiri_step_map = {s.step_id: s for s in keiri_steps}

    done_step_ids = set(
        T_WorkflowAction.objects
        .filter(instance__document_id=document, action_status_id='APPROVED')
        .values_list('step_id', flat=True)
    )

    # explicit リストを処理:
    #   keiri ステップ → step_id ごとに「経理部門」として1エントリに集約
    #   非 keiri ステップ → そのまま返す
    result = []
    seen_keiri_step_ids = set()
    for pa in explicit:
        sid = pa.step_id_id
        if sid in keiri_step_ids:
            if sid not in seen_keiri_step_ids:
                seen_keiri_step_ids.add(sid)
                step_obj = keiri_step_map.get(sid)
                post_ns = SimpleNamespace(
                    post_name=(step_obj.approver_post.post_name if step_obj and step_obj.approver_post else '')
                )
                user_ns = SimpleNamespace(user_name='経理部門', last_name='経理部門', post_cd=post_ns)
                result.append(SimpleNamespace(
                    step_order=pa.step_order,
                    man_number=user_ns,
                ))
        else:
            result.append(pa)

    # keiri ステップで T_DocumentApprover 未登録のもの（フォールバック補完）
    covered_step_ids = {pa.step_id_id for pa in explicit if pa.step_id_id}
    for step in keiri_steps:
        if step.step_id in covered_step_ids or step.step_id in done_step_ids:
            continue
        post_ns = SimpleNamespace(
            post_name=(step.approver_post.post_name if step.approver_post else '')
        )
        user_ns = SimpleNamespace(user_name='経理部門', post_cd=post_ns)
        result.append(SimpleNamespace(
            step_order=step.step_order,
            man_number=user_ns,
        ))

    return sorted(result, key=lambda x: x.step_order or 0)
```

new:
```python
def get_pending_approvers(document):
    """承認予定者（未処理）一覧を返す。

    T_DocumentApprover に登録済みの pending/draft 行を返す。
    OR_APPROVAL_SCOPES（keiri/assets）のステップは複数候補者が登録されている場合でも
    スコープごとに1エントリ（経理部門・固定資産担当など）に集約して返す。

    テンプレートが参照する属性: step_order / man_number.user_name /
    man_number.post_cd.post_name
    """
    from types import SimpleNamespace
    from .models import T_DocumentApprover, T_WorkflowAction, M_WorkflowStep

    explicit = list(
        T_DocumentApprover.objects
        .filter(document_id=document, status__in=['pending', 'draft'])
        .select_related('man_number', 'man_number__post_cd', 'step_id')
    )

    doc_type = getattr(document, 'document_type', None)
    tpl = getattr(doc_type, 'workflow_template_id', None) if doc_type else None
    if not tpl:
        return sorted(explicit, key=lambda x: x.step_order or 0)

    or_steps = list(
        M_WorkflowStep.objects
        .filter(workflow_template=tpl, allowed_bumon_scope__in=OR_APPROVAL_SCOPES)
        .select_related('approver_post')
        .order_by('step_order')
    )
    or_step_ids = {s.step_id for s in or_steps}
    or_step_map = {s.step_id: s for s in or_steps}

    done_step_ids = set(
        T_WorkflowAction.objects
        .filter(instance__document_id=document, action_status_id='APPROVED')
        .values_list('step_id', flat=True)
    )

    # explicit リストを処理:
    #   OR承認ステップ → step_id ごとにスコープの集約ラベルで1エントリに集約
    #   それ以外のステップ → そのまま返す
    result = []
    seen_or_step_ids = set()
    for pa in explicit:
        sid = pa.step_id_id
        if sid in or_step_ids:
            if sid not in seen_or_step_ids:
                seen_or_step_ids.add(sid)
                step_obj = or_step_map.get(sid)
                scope = str(step_obj.allowed_bumon_scope or '').strip().lower() if step_obj else ''
                label = OR_APPROVAL_SCOPE_LABELS.get(scope, '承認担当部門')
                post_ns = SimpleNamespace(
                    post_name=(step_obj.approver_post.post_name if step_obj and step_obj.approver_post else '')
                )
                user_ns = SimpleNamespace(user_name=label, last_name=label, post_cd=post_ns)
                result.append(SimpleNamespace(
                    step_order=pa.step_order,
                    man_number=user_ns,
                ))
        else:
            result.append(pa)

    # OR承認ステップで T_DocumentApprover 未登録のもの（フォールバック補完）
    covered_step_ids = {pa.step_id_id for pa in explicit if pa.step_id_id}
    for step in or_steps:
        if step.step_id in covered_step_ids or step.step_id in done_step_ids:
            continue
        scope = str(step.allowed_bumon_scope or '').strip().lower()
        label = OR_APPROVAL_SCOPE_LABELS.get(scope, '承認担当部門')
        post_ns = SimpleNamespace(
            post_name=(step.approver_post.post_name if step.approver_post else '')
        )
        user_ns = SimpleNamespace(user_name=label, post_cd=post_ns)
        result.append(SimpleNamespace(
            step_order=step.step_order,
            man_number=user_ns,
        ))

    return sorted(result, key=lambda x: x.step_order or 0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test expenses.tests.GetPendingApproversAggregationTest -v 2`
Expected: PASS（2 tests）

- [ ] **Step 5: Commit**

```bash
git add expenses/utils.py expenses/tests.py
git commit -m "feat: get_pending_approversをassetsスコープ対応に一般化"
```

---

### Task 4: views.py の `scope == 'keiri'` ハードコードを `is_or_approval` に置換

**Files:**
- Modify: `expenses/views.py`（import行、および承認者バリデーション・登録ロジック 6箇所）
- Test: `expenses/tests.py`

**Interfaces:**
- Consumes: `s.get('is_or_approval')`（`steps_with_candidates()` が返す辞書、Task 2 で追加）, `OR_APPROVAL_SCOPES` / `OR_APPROVAL_SCOPE_LABELS`（Task 2、Task 5 で使用）

- [ ] **Step 1: Write the failing test**

`expenses/tests.py` の末尾に追加:

```python
class ViewsOrApprovalScopeLiteralTest(TestCase):
    """views.py のステップ判定が文字列リテラル 'keiri' ではなく is_or_approval フラグを使うことを確認する"""

    def test_no_hardcoded_keiri_scope_equality_check(self):
        import inspect
        from expenses import views
        source = inspect.getsource(views)
        self.assertNotIn("allowed_bumon_scope') == 'keiri'", source)
        self.assertNotIn("scope == 'keiri'", source)

    def test_is_or_approval_flag_used_in_views(self):
        import inspect
        from expenses import views
        source = inspect.getsource(views)
        self.assertIn('is_or_approval', source)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test expenses.tests.ViewsOrApprovalScopeLiteralTest -v 2`
Expected: `test_no_hardcoded_keiri_scope_equality_check` は FAIL（現状 `== 'keiri'` が複数残っている）。`test_is_or_approval_flag_used_in_views` も FAIL（まだ views.py で未使用）。

- [ ] **Step 3: Update the import line**

old:
```python
from .utils import send_notification, steps_with_candidates, get_pending_approvers, candidates_for_step
```

new:
```python
from .utils import (
    send_notification, steps_with_candidates, get_pending_approvers, candidates_for_step,
    OR_APPROVAL_SCOPES, OR_APPROVAL_SCOPE_LABELS, OR_APPROVAL_SCOPE_SHORT_LABELS,
)
```

- [ ] **Step 4: Edit — 編集時の承認者必須チェック（`expense_edit`）**

old:
```python
                if edit_doc_type and getattr(edit_doc_type, 'workflow_template_id', None):
                    steps_for_check = steps_with_candidates(request.user, edit_doc_type.workflow_template_id)
                    for s in steps_for_check:
                        if s.get('allowed_bumon_scope') == 'keiri':
                            continue
                        if not request.POST.get(f"approver_step_{s['step_id']}"):
                            approver_missing_edit.append(str(s['step_order']))
```

new:
```python
                if edit_doc_type and getattr(edit_doc_type, 'workflow_template_id', None):
                    steps_for_check = steps_with_candidates(request.user, edit_doc_type.workflow_template_id)
                    for s in steps_for_check:
                        if s.get('is_or_approval'):
                            continue
                        if not request.POST.get(f"approver_step_{s['step_id']}"):
                            approver_missing_edit.append(str(s['step_order']))
```

- [ ] **Step 5: Edit — 新規作成時の承認者必須チェック（`expense_create`）**

old:
```python
                if resolved_doc_type and getattr(resolved_doc_type, 'workflow_template_id', None):
                    steps_for_check = steps_with_candidates(request.user, resolved_doc_type.workflow_template_id)
                    for s in steps_for_check:
                        if s.get('allowed_bumon_scope') == 'keiri':
                            continue
                        if not request.POST.get(f"approver_step_{s['step_id']}"):
                            approver_missing_create.append(str(s['step_order']))
```

new:
```python
                if resolved_doc_type and getattr(resolved_doc_type, 'workflow_template_id', None):
                    steps_for_check = steps_with_candidates(request.user, resolved_doc_type.workflow_template_id)
                    for s in steps_for_check:
                        if s.get('is_or_approval'):
                            continue
                        if not request.POST.get(f"approver_step_{s['step_id']}"):
                            approver_missing_create.append(str(s['step_order']))
```

- [ ] **Step 6: Edit — 編集時の再申請（既存承認者の再登録）**

old:
```python
                                    wf = doc_type.workflow_template_id if doc_type else None
                                    if wf:
                                        re_steps = steps_with_candidates(request.user, wf)
                                        # 非経理ステップの既存承認者を削除して再登録
                                        for s in re_steps:
                                            try:
                                                step_obj = M_WorkflowStep.objects.get(pk=s['step_id'])
                                                if s.get('allowed_bumon_scope') == 'keiri':
                                                    continue
```

new:
```python
                                    wf = doc_type.workflow_template_id if doc_type else None
                                    if wf:
                                        re_steps = steps_with_candidates(request.user, wf)
                                        # OR承認スコープ（keiri/assets）以外の既存承認者を削除して再登録
                                        for s in re_steps:
                                            try:
                                                step_obj = M_WorkflowStep.objects.get(pk=s['step_id'])
                                                if s.get('is_or_approval'):
                                                    continue
```

- [ ] **Step 7: Edit — 編集時の初回申請（OR承認登録）**

old:
```python
                            # keiriステップは候補者全員を登録（OR承認方式）、それ以外はフォームの選択値を保存
                            for s in steps:
                                if s.get('allowed_bumon_scope') == 'keiri':
                                    # keiri: 候補者全員を pending で登録（誰か1人が承認すれば次へ）
```

new:
```python
                            # OR承認スコープ（keiri/assets）は候補者全員を登録、それ以外はフォームの選択値を保存
                            for s in steps:
                                if s.get('is_or_approval'):
                                    # OR承認: 候補者全員を pending で登録（誰か1人が承認すれば次へ）
```

- [ ] **Step 8: Edit — 新規作成時の下書き保存**

old:
```python
                        for s in steps:
                            step_id = s['step_id']
                            scope = s['allowed_bumon_scope']
                            selected = None
                            field_name = f"approver_step_{step_id}"

                            if scope == 'keiri':
                                # 自動候補（あれば）をドラフト保存
                                cand = s['candidates'][0] if s['candidates'] else None
                                if cand:
                                    selected = cand['man_number']
                                else:
                                    continue
                            else:
```

new:
```python
                        for s in steps:
                            step_id = s['step_id']
                            selected = None
                            field_name = f"approver_step_{step_id}"

                            if s.get('is_or_approval'):
                                # 自動候補（あれば）をドラフト保存
                                cand = s['candidates'][0] if s['candidates'] else None
                                if cand:
                                    selected = cand['man_number']
                                else:
                                    continue
                            else:
```

- [ ] **Step 9: Edit — 新規作成時の申請確定（OR承認登録）**

old:
```python
                        for s in steps:
                            step_id = s['step_id']
                            scope = s['allowed_bumon_scope']
                            field_name = f"approver_step_{step_id}"
                            # ここから先は承認者割当の検証・生成
                            if scope == 'keiri':
                                # keiri: 候補者全員を pending で登録（OR承認方式）
                                if not s['candidates']:
                                    continue
```

new:
```python
                        for s in steps:
                            step_id = s['step_id']
                            field_name = f"approver_step_{step_id}"
                            # ここから先は承認者割当の検証・生成
                            if s.get('is_or_approval'):
                                # OR承認スコープ（keiri/assets）: 候補者全員を pending で登録
                                if not s['candidates']:
                                    continue
```

- [ ] **Step 10: Run test to verify it passes**

Run: `python manage.py test expenses.tests.ViewsOrApprovalScopeLiteralTest -v 2`
Expected: PASS（2 tests）。まだ `_build_approval_flow` と `pending_approver_map`（Task 5 で対応）に `'keiri'` 文字列自体は残るが、`== 'keiri'` という等価比較パターンはこの時点で全て解消されているはずである。もし `assertNotIn` が想定外の場所でひっかかる場合は Task 5 の対象箇所であることを確認し、Task 5 で解消する。

- [ ] **Step 11: Run full existing suite to check for regressions**

Run: `python manage.py test expenses -v 2`
Expected: 既存テストも含めて全て PASS（特に `BuildApprovalRequestMailTest` 等、views.py に依存する既存テストが壊れていないことを確認）

- [ ] **Step 12: Commit**

```bash
git add expenses/views.py expenses/tests.py
git commit -m "feat: views.pyの承認者自動割当判定をis_or_approvalフラグに一般化"
```

---

### Task 5: `_build_approval_flow()` と `pending_approver_map` を `assets` 対応に一般化

**Files:**
- Modify: `expenses/views.py`（`_build_approval_flow` 関数全体、および `approval_list` 内の `pending_approver_map` 生成箇所）
- Test: `expenses/tests.py`

**Interfaces:**
- Consumes: `OR_APPROVAL_SCOPES`, `OR_APPROVAL_SCOPE_SHORT_LABELS`（Task 2 で追加, Task 4 Step 3 で import 済み）
- Produces: `_build_approval_flow(doc_ids)` は `assets` ステップを `'[資産]'`、`keiri` ステップを `'[経理]'`（従来通り）として1エントリに集約する。

- [ ] **Step 1: Write the failing tests**

`expenses/tests.py` の `GetPendingApproversAggregationTest` の下に追加（`OrApprovalAggregationFixtureMixin` を再利用):

```python
class BuildApprovalFlowAggregationTest(OrApprovalAggregationFixtureMixin, TestCase):
    """_build_approval_flow が OR承認スコープのステップをスコープ別ラベルで集約することを確認する"""

    def _make_instance(self, doc, step):
        from expenses.models import T_WorkflowInstance
        return T_WorkflowInstance.objects.create(
            document_id=doc, workflow_template=step.workflow_template, step=step, step_order=1,
        )

    def test_assets_step_labeled_as_short_bracket_label(self):
        from expenses.views import _build_approval_flow
        doc, step = self._make_or_approval_fixture('assets')
        self._make_instance(doc, step)
        flow = _build_approval_flow([doc.document_id])
        entries = flow[doc.document_id]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['name'], '[資産]')

    def test_keiri_step_labeled_as_short_bracket_label(self):
        """回帰確認: keiri の表示ラベル '[経理]' が変わっていないこと"""
        from expenses.views import _build_approval_flow
        doc, step = self._make_or_approval_fixture('keiri')
        self._make_instance(doc, step)
        flow = _build_approval_flow([doc.document_id])
        entries = flow[doc.document_id]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['name'], '[経理]')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test expenses.tests.BuildApprovalFlowAggregationTest -v 2`
Expected: `test_assets_step_labeled_as_short_bracket_label` は FAIL（assets ステップが集約されず、個別ユーザー名2件が返る）。`test_keiri_step_labeled_as_short_bracket_label` は現状でも PASS するはずなので回帰確認のベースラインとする。

- [ ] **Step 3: Replace `_build_approval_flow()` in views.py**

old（関数全体, `def _build_approval_flow(doc_ids):` から `return approvers_by_doc` まで）:
```python
def _build_approval_flow(doc_ids):
    """doc_id → 承認フローリスト を返す。keiri ステップも補完する。
    各要素: {'name': str, 'status': 'APPROVED'|'REJECTED'|'pending', 'step_order': int, 'is_keiri': bool}
    keiri スコープのステップは複数候補者が登録されていても '[経理]' として1エントリに集約する。
    """
    from .models import M_WorkflowStep
    if not doc_ids:
        return {}

    # ① ワークフローインスタンスからテンプレートを取得
    inst_by_doc = {}
    for inst in T_WorkflowInstance.objects.filter(
        document_id__in=doc_ids
    ).select_related('workflow_template').order_by('document_id', '-started_at'):
        if inst.document_id_id not in inst_by_doc:
            inst_by_doc[inst.document_id_id] = inst

    # ② keiri ステップの step_id セットを一括収集
    template_ids = {inst.workflow_template_id for inst in inst_by_doc.values() if inst.workflow_template_id}
    keiri_step_ids = set()
    keiri_by_template = {}
    for step in M_WorkflowStep.objects.filter(
        workflow_template__in=template_ids,
        allowed_bumon_scope='keiri'
    ).order_by('step_order'):
        tid = step.workflow_template_id
        keiri_by_template.setdefault(tid, []).append(step)
        keiri_step_ids.add(step.step_id)

    # ③ T_DocumentApprover から登録済み承認者を収集
    #    keiri ステップは step_id ごとに '[経理]' として1エントリに集約
    approvers_by_doc = {}
    covered_steps = {}   # doc_id -> set of step_id
    seen_keiri = {}      # doc_id -> step_id -> entry dict（集約用参照）

    for ap in T_DocumentApprover.objects.filter(
        document_id__in=doc_ids
    ).select_related('man_number').order_by('document_id', 'step_order', 'id'):
        doc_id = ap.document_id_id
        if doc_id not in approvers_by_doc:
            approvers_by_doc[doc_id] = []
            covered_steps[doc_id] = set()
            seen_keiri[doc_id] = {}

        if ap.step_id_id and ap.step_id_id in keiri_step_ids:
            # keiri: step_id ごとに1エントリに集約
            sid = ap.step_id_id
            if sid not in seen_keiri[doc_id]:
                entry = {
                    'name': '[経理]',
                    'status': ap.status or 'pending',
                    'step_order': ap.step_order,
                    'approved_at': ap.approved_at,
                    'is_keiri': True,
                }
                seen_keiri[doc_id][sid] = entry
                approvers_by_doc[doc_id].append(entry)
            else:
                # APPROVED が1件でもあれば APPROVED を優先
                existing = seen_keiri[doc_id][sid]
                if ap.status == 'APPROVED' and existing['status'] != 'APPROVED':
                    existing['status'] = 'APPROVED'
                    existing['approved_at'] = ap.approved_at
        else:
            name = '-'
            if ap.man_number:
                name = ap.man_number.last_name or ap.man_number.user_name or '-'
            approvers_by_doc[doc_id].append({
                'name': name,
                'status': ap.status or 'pending',
                'step_order': ap.step_order,
                'approved_at': ap.approved_at,
                'is_keiri': False,
            })

        if ap.step_id_id:
            covered_steps[doc_id].add(ap.step_id_id)

    # ④ 承認済み keiri ステップを特定（T_WorkflowAction ベース）
    done_keiri = {}  # doc_id -> set of step_id
    for act in T_WorkflowAction.objects.filter(
        instance__document_id__in=doc_ids,
        action_status_id='APPROVED'
    ).values('instance__document_id_id', 'step_id'):
        doc_id = act['instance__document_id_id']
        done_keiri.setdefault(doc_id, set()).add(act['step_id'])

    # ⑤ keiri ステップを補完（T_DocumentApproverに登録がないケース）
    for doc_id in doc_ids:
        inst = inst_by_doc.get(doc_id)
        if not inst:
            continue
        keiri_steps = keiri_by_template.get(inst.workflow_template_id, [])
        covered = covered_steps.get(doc_id, set())
        done = done_keiri.get(doc_id, set())
        for step in keiri_steps:
            if step.step_id in covered:
                continue
            approvers_by_doc.setdefault(doc_id, []).append({
                'name': '[経理]',
                'status': 'APPROVED' if step.step_id in done else 'pending',
                'step_order': step.step_order,
                'approved_at': None,
                'is_keiri': True,
            })

    # ⑥ step_order 順に整列
    for doc_id in approvers_by_doc:
        approvers_by_doc[doc_id].sort(key=lambda x: (x['step_order'], x['name']))

    return approvers_by_doc
```

new:
```python
def _build_approval_flow(doc_ids):
    """doc_id → 承認フローリスト を返す。OR承認スコープ（keiri/assets）のステップも補完する。
    各要素: {'name': str, 'status': 'APPROVED'|'REJECTED'|'pending', 'step_order': int, 'is_or_approval': bool}
    OR承認スコープのステップは複数候補者が登録されていても、スコープごとに1エントリ
    （例: '[経理]' '[資産]'）に集約する。
    """
    from .models import M_WorkflowStep
    if not doc_ids:
        return {}

    # ① ワークフローインスタンスからテンプレートを取得
    inst_by_doc = {}
    for inst in T_WorkflowInstance.objects.filter(
        document_id__in=doc_ids
    ).select_related('workflow_template').order_by('document_id', '-started_at'):
        if inst.document_id_id not in inst_by_doc:
            inst_by_doc[inst.document_id_id] = inst

    # ② OR承認スコープのステップの step_id セットを一括収集
    template_ids = {inst.workflow_template_id for inst in inst_by_doc.values() if inst.workflow_template_id}
    or_step_ids = set()
    or_by_template = {}
    or_step_scope = {}
    for step in M_WorkflowStep.objects.filter(
        workflow_template__in=template_ids,
        allowed_bumon_scope__in=OR_APPROVAL_SCOPES
    ).order_by('step_order'):
        tid = step.workflow_template_id
        or_by_template.setdefault(tid, []).append(step)
        or_step_ids.add(step.step_id)
        or_step_scope[step.step_id] = str(step.allowed_bumon_scope or '').strip().lower()

    # ③ T_DocumentApprover から登録済み承認者を収集
    #    OR承認スコープのステップは step_id ごとに集約ラベルで1エントリに集約
    approvers_by_doc = {}
    covered_steps = {}   # doc_id -> set of step_id
    seen_or = {}         # doc_id -> step_id -> entry dict（集約用参照）

    for ap in T_DocumentApprover.objects.filter(
        document_id__in=doc_ids
    ).select_related('man_number').order_by('document_id', 'step_order', 'id'):
        doc_id = ap.document_id_id
        if doc_id not in approvers_by_doc:
            approvers_by_doc[doc_id] = []
            covered_steps[doc_id] = set()
            seen_or[doc_id] = {}

        if ap.step_id_id and ap.step_id_id in or_step_ids:
            # OR承認: step_id ごとに1エントリに集約
            sid = ap.step_id_id
            if sid not in seen_or[doc_id]:
                scope = or_step_scope.get(sid, '')
                label = f"[{OR_APPROVAL_SCOPE_SHORT_LABELS.get(scope, '承認')}]"
                entry = {
                    'name': label,
                    'status': ap.status or 'pending',
                    'step_order': ap.step_order,
                    'approved_at': ap.approved_at,
                    'is_or_approval': True,
                }
                seen_or[doc_id][sid] = entry
                approvers_by_doc[doc_id].append(entry)
            else:
                # APPROVED が1件でもあれば APPROVED を優先
                existing = seen_or[doc_id][sid]
                if ap.status == 'APPROVED' and existing['status'] != 'APPROVED':
                    existing['status'] = 'APPROVED'
                    existing['approved_at'] = ap.approved_at
        else:
            name = '-'
            if ap.man_number:
                name = ap.man_number.last_name or ap.man_number.user_name or '-'
            approvers_by_doc[doc_id].append({
                'name': name,
                'status': ap.status or 'pending',
                'step_order': ap.step_order,
                'approved_at': ap.approved_at,
                'is_or_approval': False,
            })

        if ap.step_id_id:
            covered_steps[doc_id].add(ap.step_id_id)

    # ④ 承認済み OR承認ステップを特定（T_WorkflowAction ベース）
    done_or = {}  # doc_id -> set of step_id
    for act in T_WorkflowAction.objects.filter(
        instance__document_id__in=doc_ids,
        action_status_id='APPROVED'
    ).values('instance__document_id_id', 'step_id'):
        doc_id = act['instance__document_id_id']
        done_or.setdefault(doc_id, set()).add(act['step_id'])

    # ⑤ OR承認ステップを補完（T_DocumentApproverに登録がないケース）
    for doc_id in doc_ids:
        inst = inst_by_doc.get(doc_id)
        if not inst:
            continue
        or_steps = or_by_template.get(inst.workflow_template_id, [])
        covered = covered_steps.get(doc_id, set())
        done = done_or.get(doc_id, set())
        for step in or_steps:
            if step.step_id in covered:
                continue
            scope = or_step_scope.get(step.step_id, '')
            label = f"[{OR_APPROVAL_SCOPE_SHORT_LABELS.get(scope, '承認')}]"
            approvers_by_doc.setdefault(doc_id, []).append({
                'name': label,
                'status': 'APPROVED' if step.step_id in done else 'pending',
                'step_order': step.step_order,
                'approved_at': None,
                'is_or_approval': True,
            })

    # ⑥ step_order 順に整列
    for doc_id in approvers_by_doc:
        approvers_by_doc[doc_id].sort(key=lambda x: (x['step_order'], x['name']))

    return approvers_by_doc
```

- [ ] **Step 4: Replace `pending_approver_map` generation in `approval_list`**

old:
```python
        did = pa.document_id_id
        if did not in pending_approver_map:
            # keiri スコープのステップは個人名でなく「経理部門」と表示
            if pa.step_id and getattr(pa.step_id, 'allowed_bumon_scope', '') == 'keiri':
                pending_approver_map[did] = '経理部門'
            else:
                pending_approver_map[did] = pa.man_number.user_name
```

new:
```python
        did = pa.document_id_id
        if did not in pending_approver_map:
            # OR承認スコープ（keiri/assets）のステップは個人名でなく集約ラベルを表示
            scope = str(getattr(pa.step_id, 'allowed_bumon_scope', '') or '').strip().lower()
            if pa.step_id and scope in OR_APPROVAL_SCOPES:
                pending_approver_map[did] = OR_APPROVAL_SCOPE_LABELS.get(scope, pa.man_number.user_name)
            else:
                pending_approver_map[did] = pa.man_number.user_name
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test expenses.tests.BuildApprovalFlowAggregationTest expenses.tests.ViewsOrApprovalScopeLiteralTest -v 2`
Expected: PASS（4 tests）。`ViewsOrApprovalScopeLiteralTest` も改めて通すことで `'keiri'` への等価比較が views.py に一切残っていないことを再確認する。

- [ ] **Step 6: Run full existing suite to check for regressions**

Run: `python manage.py test expenses -v 2`
Expected: 全テスト PASS

- [ ] **Step 7: Commit**

```bash
git add expenses/views.py expenses/tests.py
git commit -m "feat: 承認フロー表示(_build_approval_flow/pending_approver_map)をassets対応に一般化"
```

---

### Task 6: テンプレートを `is_or_approval` フラグ対応に変更

**Files:**
- Modify: `expenses/templates/expenses/expense_form.html`（391行目付近）
- Modify: `expenses/templates/expenses/travel_expense_form.html`（509行目付近）
- Test: `expenses/tests.py`

**Interfaces:**
- Consumes: `s.is_or_approval`（`steps_with_candidates()` が `workflow_steps` コンテキスト変数として渡すステップ辞書、Task 2 で追加）

- [ ] **Step 1: Write the failing test**

`expenses/tests.py` の末尾に追加:

```python
class TemplateOrApprovalFlagTest(TestCase):
    """承認者選択フォームが is_or_approval フラグで自動回付メッセージを出すことを確認する"""

    def _read_template(self, name):
        import os
        from django.apps import apps
        app_dir = apps.get_app_config('expenses').path
        path = os.path.join(app_dir, 'templates', 'expenses', name)
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_expense_form_uses_is_or_approval_flag(self):
        source = self._read_template('expense_form.html')
        self.assertIn('s.is_or_approval', source)
        self.assertNotIn("s.allowed_bumon_scope == 'keiri'", source)

    def test_travel_expense_form_uses_is_or_approval_flag(self):
        source = self._read_template('travel_expense_form.html')
        self.assertIn('s.is_or_approval', source)
        self.assertNotIn("s.allowed_bumon_scope == 'keiri'", source)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test expenses.tests.TemplateOrApprovalFlagTest -v 2`
Expected: FAIL（テンプレートにまだ `s.is_or_approval` が存在しない）

- [ ] **Step 3: Edit `expense_form.html`**

old（391-392行目付近）:
```html
                        {% if s.allowed_bumon_scope == 'keiri' %}
                            <div class="form-text">経理ステップは自動で回付されます（選択不要）。</div>
                        {% elif s.allowed_bumon_scope == 'others' %}
```

new:
```html
                        {% if s.is_or_approval %}
                            <div class="form-text">このステップは自動で回付されます（選択不要）。</div>
                        {% elif s.allowed_bumon_scope == 'others' %}
```

- [ ] **Step 4: Edit `travel_expense_form.html`**

old（509-511行目付近）:
```html
                        {% if s.allowed_bumon_scope == 'keiri' %}
                            <div class="form-text">経理ステップは自動で回付されます（選択不要）。</div>
                        {% elif s.allowed_bumon_scope == 'others' %}
```

new:
```html
                        {% if s.is_or_approval %}
                            <div class="form-text">このステップは自動で回付されます（選択不要）。</div>
                        {% elif s.allowed_bumon_scope == 'others' %}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test expenses.tests.TemplateOrApprovalFlagTest -v 2`
Expected: PASS（2 tests）

- [ ] **Step 6: Run full suite for final regression check**

Run: `python manage.py test expenses -v 2`
Expected: 全テスト PASS（Task 1〜6 で追加したテストを含む）

- [ ] **Step 7: Commit**

```bash
git add expenses/templates/expenses/expense_form.html expenses/templates/expenses/travel_expense_form.html expenses/tests.py
git commit -m "feat: 承認者選択フォームをis_or_approvalフラグ対応に変更し固定資産スコープの自動回付に対応"
```

---

## 完了後の運用手順（ユーザー向け、コード変更不要）

実装完了後、固定資産の承認ステップを自動割当にするには:

1. `/settings/master/m_user/` で対象ユーザーを編集し、ロールに `assets` を追加する（Django Admin の `M_UserRole` インラインでも可）。
2. `/settings/master/m_workflow_step/` で対象ステップの「部門範囲」を `固定資産` に設定する。

これにより、当該ステップは申請者の選択UIが表示されず、`role='assets'` の全ユーザーが自動的に承認待ち（OR承認）として登録される。
