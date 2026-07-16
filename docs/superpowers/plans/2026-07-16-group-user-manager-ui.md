# グループ/ユーザーマネージャーUI 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/settings/master/m_group/`・`/settings/master/m_user/` の一覧画面を、階層ツリー（グループ）とフィルタ検索（ユーザー）の専用UIに差し替える。

**Architecture:** `settings_master_list` の冒頭で `m_group`/`m_user` のみ `views_org_manager.py` の専用ビューへ委譲。追加・編集・削除は既存の `settings_master_create/edit/delete` を再利用し、一覧テンプレート2枚と AJAX トグル1本だけを新設する。DB変更なし。

**Tech Stack:** Django 5.2.6 / MySQL 8.0(本番共用) / Bootstrap 5 + swiss.css / Django TestCase

**Spec:** `docs/superpowers/specs/2026-07-16-group-user-manager-ui-design.md`

## Global Constraints

- **本番DB直結。破壊的SQL・`flush`・データ削除禁止。** ランタイム確認は読み取り専用で行う。
- テストは必ず `--keepdb` 付き（`test_expense_db` はクローン済み）。**`DJANGO_TEST_DB_NAME=expense_db` は絶対に使わない。**
- テスト実行コマンド（Windows側から）: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test <target> --keepdb -v 2"`
- git は WSL 側で操作し、**変更ファイルを明示的に `git add`**（`git add -A` 禁止。リポジトリに幽霊ファイルがあるため）。コミットは master 直接。
- コミットメッセージ末尾に `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` を付ける。
- マイグレーション作成禁止（本機能はDB変更なしで完結する）。
- UIラベル・コメントは日本語。既存の Bootstrap ベーステンプレート（`settings_master_list.html` 参照)のクラス使いを踏襲。

---

### Task 1: `build_group_tree` 純粋関数（木構築・循環/orphan防御）

**Files:**
- Create: `expenses/views_org_manager.py`
- Test: `expenses/test_org_manager.py`

**Interfaces:**
- Produces: `build_group_tree(groups: list[M_Group]) -> list[dict]`
  各dictは `{'group': M_Group, 'depth': int, 'indent': int, 'is_orphan': bool}`。DFS順（同階層は group_cd 昇順）。`indent = depth * 18`（px）。
  - `upper_group_cd` が空/None → ルート
  - `upper_group_cd` が存在しないコード → orphan としてルート扱い（`is_orphan=True`）
  - 循環参照ノード → ルート扱い（`is_orphan=True`）、無限ループしない

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_org_manager.py` を新規作成:

```python
"""グループ/ユーザーマネージャー画面のテスト"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import M_BelongTo, M_Bumon, M_Group, M_Post

User = get_user_model()


class BuildGroupTreeTests(TestCase):
    """build_group_tree 純粋関数のテスト"""

    def test_通常階層はDFS順で同階層はコード昇順(self):
        from expenses.views_org_manager import build_group_tree
        M_Group.objects.create(group_cd='200', group_name='営業本部', upper_group_cd='')
        M_Group.objects.create(group_cd='100', group_name='管理本部', upper_group_cd='')
        M_Group.objects.create(group_cd='110', group_name='経理部', upper_group_cd='100')
        M_Group.objects.create(group_cd='111', group_name='経理課', upper_group_cd='110')
        nodes = build_group_tree(list(M_Group.objects.all()))
        result = [(n['group'].group_cd, n['depth']) for n in nodes]
        self.assertEqual(
            result, [('100', 0), ('110', 1), ('111', 2), ('200', 0)])
        self.assertEqual(nodes[1]['indent'], 18)
        self.assertFalse(any(n['is_orphan'] for n in nodes))

    def test_上位コードが存在しない部署はorphanのルート扱い(self):
        from expenses.views_org_manager import build_group_tree
        M_Group.objects.create(group_cd='300', group_name='孤児部署', upper_group_cd='999')
        nodes = build_group_tree(list(M_Group.objects.all()))
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]['depth'], 0)
        self.assertTrue(nodes[0]['is_orphan'])

    def test_循環参照でも無限ループせず全件出る(self):
        from expenses.views_org_manager import build_group_tree
        M_Group.objects.create(group_cd='A', group_name='A部', upper_group_cd='B')
        M_Group.objects.create(group_cd='B', group_name='B部', upper_group_cd='A')
        nodes = build_group_tree(list(M_Group.objects.all()))
        self.assertEqual(len(nodes), 2)
        self.assertTrue(all(n['is_orphan'] for n in nodes))

    def test_upper_group_cdがNoneでもルート扱い(self):
        from expenses.views_org_manager import build_group_tree
        M_Group.objects.create(group_cd='100', group_name='本社', upper_group_cd=None)
        nodes = build_group_tree(list(M_Group.objects.all()))
        self.assertEqual(nodes[0]['depth'], 0)
        self.assertFalse(nodes[0]['is_orphan'])
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_org_manager --keepdb -v 2"`
Expected: 4件 ERROR（`ModuleNotFoundError: No module named 'expenses.views_org_manager'`）

- [ ] **Step 3: 最小実装を書く**

`expenses/views_org_manager.py` を新規作成:

```python
"""グループ/ユーザーマネージャー（m_group / m_user 専用一覧ビュー）

GSessionのグループマネージャー/ユーザマネージャーUIを参考に、
汎用マスタ画面 (settings_master_list) から委譲される専用一覧を提供する。
追加・編集・削除は既存の settings_master_* ビューを再利用する。
"""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .models import M_BelongTo, M_Bumon, M_Group, M_Post, M_User


def build_group_tree(groups):
    """M_Groupのリストから表示順（DFS・同階層はgroup_cd昇順）のノードリストを作る。

    upper_group_cd が空/None はルート。存在しないコードを指す場合(orphan)と
    循環参照ノードはルート扱い(is_orphan=True)にして無限ループを防ぐ。
    """
    by_cd = {g.group_cd: g for g in groups}
    children = {}
    roots = []
    orphans = []
    for g in groups:
        up = g.upper_group_cd or ''
        if not up:
            roots.append(g)
        elif up in by_cd:
            children.setdefault(up, []).append(g)
        else:
            orphans.append(g)

    nodes = []
    visited = set()

    def walk(g, depth, is_orphan=False):
        if g.group_cd in visited:
            return
        visited.add(g.group_cd)
        nodes.append({
            'group': g, 'depth': depth,
            'indent': depth * 18, 'is_orphan': is_orphan,
        })
        for c in sorted(children.get(g.group_cd, []), key=lambda x: x.group_cd):
            walk(c, depth + 1)

    for g in sorted(roots, key=lambda x: x.group_cd):
        walk(g, 0)
    for g in sorted(orphans, key=lambda x: x.group_cd):
        walk(g, 0, is_orphan=True)
    # 循環参照でどのルートからも到達できなかった残りを回収
    for g in sorted(groups, key=lambda x: x.group_cd):
        if g.group_cd not in visited:
            walk(g, 0, is_orphan=True)
    return nodes
```

- [ ] **Step 4: テストが通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_org_manager --keepdb -v 2"`
Expected: OK (4 tests)

- [ ] **Step 5: コミット**

```bash
wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && git add expenses/views_org_manager.py expenses/test_org_manager.py && git commit -m 'feat: 部署ツリー構築関数build_group_treeを追加（循環・orphan防御付き）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>'"
```

---

### Task 2: グループマネージャー一覧ビュー＋テンプレート＋委譲分岐

**Files:**
- Modify: `expenses/views_org_manager.py`（Task 1 の続きに追記）
- Modify: `expenses/views.py:7` 付近（import追加）と `settings_master_list`（views.py:6319）冒頭
- Create: `expenses/templates/expenses/group_manager_list.html`
- Test: `expenses/test_org_manager.py`

**Interfaces:**
- Consumes: `build_group_tree`（Task 1）
- Produces: `group_manager_list(request)` ビュー。`/settings/master/m_group/` でツリー画面が返る。各nodeに `members`（M_Userのリスト）が付く。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_org_manager.py` に追記:

```python
class GroupManagerListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.login_user = User.objects.create_user(
            username='tester', man_number='9001',
            user_name='テスト太郎', password='pass')
        root = M_Group.objects.create(
            group_cd='100', group_name='管理本部', upper_group_cd='')
        child = M_Group.objects.create(
            group_cd='110', group_name='経理部', upper_group_cd='100')
        member = User.objects.create_user(
            username='member1', man_number='9002',
            user_name='所属花子', password='pass')
        M_BelongTo.objects.create(man_number=member, group_cd=child)

    def test_m_groupの一覧はツリー画面が返る(self):
        self.client.force_login(self.login_user)
        res = self.client.get(
            reverse('expenses:settings_master_list', args=['m_group']))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'expenses/group_manager_list.html')
        self.assertContains(res, '経理部')
        self.assertContains(res, '所属花子')  # 展開用に埋め込まれる所属ユーザー名

    def test_他のマスタキーは従来の汎用画面のまま(self):
        self.client.force_login(self.login_user)
        res = self.client.get(
            reverse('expenses:settings_master_list', args=['m_bumon']))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'expenses/settings_master_list.html')
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_org_manager.GroupManagerListViewTests --keepdb -v 2"`
Expected: FAIL（`group_manager_list.html` が使われず汎用画面が返る）

- [ ] **Step 3: ビューを実装**

`expenses/views_org_manager.py` の末尾に追記:

```python
@login_required
def group_manager_list(request):
    """部署マスタ: 階層ツリー一覧（GSessionグループマネージャー相当）"""
    groups = list(M_Group.objects.all())
    nodes = build_group_tree(groups)

    # 所属ユーザーを部署ごとにまとめてページ表示時に一括埋め込み（AJAXなし）
    members_map = {}
    belongs = (M_BelongTo.objects
               .select_related('man_number')
               .order_by('man_number__man_number'))
    for b in belongs:
        members_map.setdefault(b.group_cd_id, []).append(b.man_number)
    for node in nodes:
        node['members'] = members_map.get(node['group'].group_cd, [])

    return render(request, 'expenses/group_manager_list.html', {
        'nodes': nodes,
        'total_count': len(groups),
    })
```

- [ ] **Step 4: 委譲分岐を追加**

`expenses/views.py` の views_assets_register インポート（7行目付近）の直後に追加（`user_manager_list` 等は Task 4 で実装後にこの行へ追記する。未実装名を先に import すると ImportError になるので、このTaskでは1つだけ）:

```python
from .views_org_manager import group_manager_list
```

`settings_master_list`（views.py:6319 `def settings_master_list` 直下）の関数冒頭に分岐を追加:

```python
@login_required
def settings_master_list(request, master_key):
    """マスタ一覧"""
    # m_group / m_user は専用マネージャー画面へ委譲（views_org_manager.py）
    if master_key == 'm_group':
        return group_manager_list(request)
    from django.db.models import CharField, TextField
    ...（既存コードそのまま）
```

- [ ] **Step 5: テンプレートを作成**

`expenses/templates/expenses/group_manager_list.html` を新規作成:

```html
{% extends "expenses/base.html" %}
{% load static %}

{% block content %}
<div>
    <!-- ページヘッド -->
    <div class="d-flex align-items-center justify-content-between mb-3">
        <div class="d-flex align-items-center gap-3">
            <a href="{% url 'expenses:settings_master_home' %}" class="btn btn-outline-secondary btn-sm">
                <i class="fas fa-arrow-left me-1"></i>マスタ一覧
            </a>
            <div>
                <h2 class="mb-0">所属部署マスタ</h2>
                <p class="text-muted small mb-0">m_group ・ 階層ツリー表示（全 {{ total_count }} 部署）</p>
            </div>
        </div>
        <div class="d-flex gap-2">
            <a href="{% url 'expenses:settings_master_csv' 'm_group' %}" class="btn btn-outline-secondary btn-sm">
                <i class="fas fa-download me-1"></i>データ出力
            </a>
            <a href="{% url 'expenses:settings_master_create' 'm_group' %}" class="btn btn-primary btn-sm">
                <i class="fas fa-plus me-1"></i>新規追加
            </a>
        </div>
    </div>

    <!-- ツリーテーブル -->
    <div class="card" style="min-width:520px; max-width:960px;">
        <div class="table-responsive">
            <table class="table table-hover table-sm mb-0 align-middle">
                <thead class="table-light">
                    <tr>
                        <th>部署名（コード）</th>
                        <th style="width:110px" class="text-center">所属人数</th>
                        <th style="width:250px" class="text-center">操作</th>
                    </tr>
                </thead>
                <tbody>
                {% for node in nodes %}
                    <tr>
                        <td class="small">
                            <span style="display:inline-block; width:{{ node.indent }}px;"></span>
                            {% if node.depth > 0 %}<i class="fas fa-level-up-alt fa-rotate-90 text-muted me-1"></i>{% endif %}
                            <strong>{{ node.group.group_name }}</strong>
                            <span class="text-muted">({{ node.group.group_cd }})</span>
                            {% if node.is_orphan %}
                                <span class="badge bg-warning text-dark ms-1"
                                      title="上位部署コード「{{ node.group.upper_group_cd }}」が存在しないか、循環参照になっています">上位不明</span>
                            {% endif %}
                        </td>
                        <td class="text-center">
                            {% if node.members %}
                            <button class="btn btn-outline-secondary btn-sm py-0 px-2" type="button"
                                    data-bs-toggle="collapse" data-bs-target="#members-{{ forloop.counter }}"
                                    title="所属ユーザーを表示">
                                <i class="fas fa-users me-1"></i>{{ node.members|length }}
                            </button>
                            {% else %}
                            <span class="text-muted small">0</span>
                            {% endif %}
                        </td>
                        <td class="text-center">
                            <div class="d-flex gap-1 justify-content-center">
                                <a href="{% url 'expenses:settings_master_create' 'm_group' %}?upper_group_cd={{ node.group.group_cd }}"
                                   class="btn btn-outline-secondary btn-sm py-0 px-2" title="この部署の配下に追加">
                                    <i class="fas fa-plus me-1"></i>配下に追加
                                </a>
                                <a href="{% url 'expenses:settings_master_edit' 'm_group' node.group.group_cd %}"
                                   class="btn btn-outline-primary btn-sm py-0 px-2" title="編集">
                                    <i class="fas fa-edit"></i>
                                </a>
                                <form method="post" action="{% url 'expenses:settings_master_delete' 'm_group' node.group.group_cd %}"
                                      onsubmit="return confirm('「{{ node.group.group_name }}」を削除しますか？\n所属ユーザーがいる部署は削除できません。')">
                                    {% csrf_token %}
                                    <button type="submit" class="btn btn-outline-danger btn-sm py-0 px-2" title="削除">
                                        <i class="fas fa-trash-alt"></i>
                                    </button>
                                </form>
                            </div>
                        </td>
                    </tr>
                    {% if node.members %}
                    <tr class="collapse" id="members-{{ forloop.counter }}">
                        <td colspan="3" class="small bg-light" style="padding-left:{{ node.indent|add:40 }}px;">
                            {% for u in node.members %}
                                <div class="py-1">
                                    <i class="fas fa-user text-muted me-1"></i>
                                    {{ u.user_name }}（{{ u.man_number }}）
                                    {% if not u.is_active %}<span class="badge bg-secondary ms-1">無効</span>{% endif %}
                                </div>
                            {% endfor %}
                        </td>
                    </tr>
                    {% endif %}
                {% empty %}
                    <tr>
                        <td colspan="3" class="text-center text-muted py-4">データがありません</td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 6: テストが通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_org_manager --keepdb -v 2"`
Expected: OK (6 tests)

- [ ] **Step 7: コミット**

```bash
wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && git add expenses/views_org_manager.py expenses/views.py expenses/templates/expenses/group_manager_list.html expenses/test_org_manager.py && git commit -m 'feat: 部署マスタ一覧を階層ツリー画面に差し替え（所属ユーザー展開付き）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>'"
```

---

### Task 3: 「配下に追加」= 新規作成フォームのGET initial対応

**Files:**
- Modify: `expenses/views.py` `settings_master_create`（views.py:6372付近）
- Test: `expenses/test_org_manager.py`

**Interfaces:**
- Produces: `settings_master_create` が GETパラメータのうちフォームフィールド名に一致するものを initial にセットする（全マスタ共通の汎用動作。`?upper_group_cd=100` で上位部署が初期選択される）。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_org_manager.py` に追記:

```python
class MasterCreateInitialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.login_user = User.objects.create_user(
            username='tester2', man_number='9003',
            user_name='テスト次郎', password='pass')

    def test_GETパラメータがフォーム初期値に入る(self):
        self.client.force_login(self.login_user)
        res = self.client.get(
            reverse('expenses:settings_master_create', args=['m_group'])
            + '?upper_group_cd=100')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.context['form'].initial.get('upper_group_cd'), '100')

    def test_フォームに存在しないGETパラメータは無視される(self):
        self.client.force_login(self.login_user)
        res = self.client.get(
            reverse('expenses:settings_master_create', args=['m_group'])
            + '?evil_param=x')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('evil_param', res.context['form'].initial)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_org_manager.MasterCreateInitialTests --keepdb -v 2"`
Expected: FAIL（initial が空）

- [ ] **Step 3: 実装**

`expenses/views.py` の `settings_master_create` 内、GET時の `form = FormClass()` を差し替え:

```python
    else:
        # GETパラメータのうちフォームフィールド名に一致するものを初期値に
        # （部署ツリーの「配下に追加」が ?upper_group_cd=xxx を渡してくる）
        initial = {
            k: v for k, v in request.GET.items()
            if k in FormClass.base_fields
        }
        form = FormClass(initial=initial)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_org_manager --keepdb -v 2"`
Expected: OK (8 tests)

- [ ] **Step 5: コミット**

```bash
wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && git add expenses/views.py expenses/test_org_manager.py && git commit -m 'feat: マスタ新規作成フォームにGETパラメータ初期値対応（配下に追加用）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>'"
```

---

### Task 4: ユーザーマネージャー一覧ビュー＋テンプレート＋委譲分岐

**Files:**
- Modify: `expenses/views_org_manager.py`（追記）
- Modify: `expenses/views.py`（import追記・委譲分岐追記）
- Create: `expenses/templates/expenses/user_manager_list.html`
- Test: `expenses/test_org_manager.py`

**Interfaces:**
- Consumes: なし（独立）
- Produces: `user_manager_list(request)` ビュー。GETパラメータ: `bumon` / `post` / `group` / `status`（`active`(デフォルト)/`inactive`/`all`）/ `q`（社員番号 or 氏名 icontains）/ `page`。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_org_manager.py` に追記:

```python
class UserManagerListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.login_user = User.objects.create_user(
            username='tester3', man_number='9004',
            user_name='テスト三郎', password='pass')
        cls.bumon = M_Bumon.objects.create(bumon_cd='B01', bumon_name='管理部門')
        cls.post = M_Post.objects.create(post_cd='P01', post_name='課長', post_order=10)
        cls.group = M_Group.objects.create(
            group_cd='110', group_name='経理部', upper_group_cd='')
        cls.active_user = User.objects.create_user(
            username='u_active', man_number='1001', user_name='有効太郎',
            password='pass', bumon_cd=cls.bumon, post_cd=cls.post, is_active=True)
        cls.inactive_user = User.objects.create_user(
            username='u_inactive', man_number='1002', user_name='無効花子',
            password='pass', is_active=False)
        M_BelongTo.objects.create(man_number=cls.active_user, group_cd=cls.group)

    def _get(self, params=''):
        self.client.force_login(self.login_user)
        url = reverse('expenses:settings_master_list', args=['m_user'])
        return self.client.get(url + params)

    def test_m_userの一覧は専用画面でデフォルト有効のみ表示(self):
        res = self._get()
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'expenses/user_manager_list.html')
        self.assertContains(res, '有効太郎')
        self.assertNotContains(res, '無効花子')

    def test_statusフィルタallで無効ユーザーも表示(self):
        res = self._get('?status=all')
        self.assertContains(res, '有効太郎')
        self.assertContains(res, '無効花子')

    def test_所属部署フィルタ(self):
        res = self._get('?group=110')
        self.assertContains(res, '有効太郎')
        self.assertNotContains(res, 'テスト三郎')  # 未所属のログインユーザーは出ない

    def test_キーワード検索は社員番号と氏名を対象(self):
        res = self._get('?q=1001')
        self.assertContains(res, '有効太郎')
        res = self._get('?q=太郎')
        self.assertContains(res, '有効太郎')

    def test_所属部署列と未所属表示(self):
        res = self._get('?status=all')
        self.assertContains(res, '経理部')      # active_user の所属部署
        self.assertContains(res, '（未所属）')  # inactive_user は未所属
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_org_manager.UserManagerListViewTests --keepdb -v 2"`
Expected: FAIL（汎用画面が返る）

- [ ] **Step 3: ビューを実装**

`expenses/views_org_manager.py` の末尾に追記:

```python
@login_required
def user_manager_list(request):
    """ユーザーマスタ: フィルタ検索一覧（GSessionユーザマネージャー相当）"""
    from urllib.parse import urlencode

    bumon = request.GET.get('bumon', '')
    post = request.GET.get('post', '')
    group = request.GET.get('group', '')
    status = request.GET.get('status', 'active')  # active / inactive / all
    q = request.GET.get('q', '').strip()

    qs = (M_User.objects
          .select_related('bumon_cd', 'post_cd')
          .prefetch_related('belongs__group_cd'))
    if bumon:
        qs = qs.filter(bumon_cd=bumon)
    if post:
        qs = qs.filter(post_cd=post)
    if group:
        qs = qs.filter(belongs__group_cd=group)
    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'inactive':
        qs = qs.filter(is_active=False)
    if q:
        qs = qs.filter(Q(man_number__icontains=q) | Q(user_name__icontains=q))

    qs = qs.order_by('man_number').distinct()
    total_count = qs.count()
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    filters = {'bumon': bumon, 'post': post, 'group': group,
               'status': status, 'q': q}
    qstring = urlencode({k: v for k, v in filters.items() if v})

    return render(request, 'expenses/user_manager_list.html', {
        'page_obj': page_obj,
        'total_count': total_count,
        'bumon_list': M_Bumon.objects.order_by('bumon_cd'),
        'post_list': M_Post.objects.order_by('post_order'),
        'group_list': M_Group.objects.order_by('group_cd'),
        'filters': filters,
        'qstring': qstring,
    })
```

- [ ] **Step 4: 委譲分岐とimportを追加**

`expenses/views.py` の import を更新:

```python
from .views_org_manager import group_manager_list, user_manager_list
```

`settings_master_list` の委譲分岐に追記:

```python
    # m_group / m_user は専用マネージャー画面へ委譲（views_org_manager.py）
    if master_key == 'm_group':
        return group_manager_list(request)
    if master_key == 'm_user':
        return user_manager_list(request)
```

- [ ] **Step 5: テンプレートを作成**

`expenses/templates/expenses/user_manager_list.html` を新規作成:

```html
{% extends "expenses/base.html" %}
{% load static %}

{% block content %}
<div>
    <!-- ページヘッド -->
    <div class="d-flex align-items-center justify-content-between mb-3">
        <div class="d-flex align-items-center gap-3">
            <a href="{% url 'expenses:settings_master_home' %}" class="btn btn-outline-secondary btn-sm">
                <i class="fas fa-arrow-left me-1"></i>マスタ一覧
            </a>
            <div>
                <h2 class="mb-0">ユーザーマスタ</h2>
                <p class="text-muted small mb-0">m_user ・ {{ total_count }} 件</p>
            </div>
        </div>
        <div class="d-flex gap-2">
            <a href="{% url 'expenses:settings_master_csv' 'm_user' %}" class="btn btn-outline-secondary btn-sm">
                <i class="fas fa-download me-1"></i>データ出力
            </a>
            <a href="{% url 'expenses:settings_master_create' 'm_user' %}" class="btn btn-primary btn-sm">
                <i class="fas fa-plus me-1"></i>新規追加
            </a>
        </div>
    </div>

    <!-- フィルタバー -->
    <form method="get" class="mb-3">
        <div class="d-flex gap-2 align-items-center flex-wrap">
            <select name="bumon" class="form-select form-select-sm" style="width:auto;">
                <option value="">部門: すべて</option>
                {% for b in bumon_list %}
                <option value="{{ b.bumon_cd }}" {% if filters.bumon == b.bumon_cd %}selected{% endif %}>{{ b.bumon_name }}</option>
                {% endfor %}
            </select>
            <select name="post" class="form-select form-select-sm" style="width:auto;">
                <option value="">役職: すべて</option>
                {% for p in post_list %}
                <option value="{{ p.post_cd }}" {% if filters.post == p.post_cd %}selected{% endif %}>{{ p.post_name }}</option>
                {% endfor %}
            </select>
            <select name="group" class="form-select form-select-sm" style="width:auto;">
                <option value="">所属部署: すべて</option>
                {% for g in group_list %}
                <option value="{{ g.group_cd }}" {% if filters.group == g.group_cd %}selected{% endif %}>{{ g.group_name }}</option>
                {% endfor %}
            </select>
            <select name="status" class="form-select form-select-sm" style="width:auto;">
                <option value="active" {% if filters.status == 'active' %}selected{% endif %}>状態: 有効のみ</option>
                <option value="inactive" {% if filters.status == 'inactive' %}selected{% endif %}>状態: 無効のみ</option>
                <option value="all" {% if filters.status == 'all' %}selected{% endif %}>状態: すべて</option>
            </select>
            <div class="input-group input-group-sm" style="width:240px;">
                <span class="input-group-text"><i class="fas fa-search"></i></span>
                <input type="text" name="q" value="{{ filters.q }}" class="form-control"
                       placeholder="社員番号・氏名" autocomplete="off">
            </div>
            <button type="submit" class="btn btn-sm btn-primary" style="white-space:nowrap;">検索</button>
            <a href="{% url 'expenses:settings_master_list' 'm_user' %}" class="btn btn-sm btn-outline-secondary" style="white-space:nowrap;">クリア</a>
        </div>
    </form>

    <!-- テーブル -->
    <div class="card" style="display:inline-block; min-width:700px; max-width:100%;">
        <div class="table-responsive">
            <table class="table table-hover table-sm mb-0 align-middle" style="width:auto; min-width:100%;">
                <thead class="table-light">
                    <tr>
                        <th>社員番号</th>
                        <th>氏名</th>
                        <th>部門</th>
                        <th>役職</th>
                        <th>所属部署</th>
                        <th class="text-center">状態</th>
                        <th style="width:140px" class="text-center">操作</th>
                    </tr>
                </thead>
                <tbody>
                {% for u in page_obj %}
                    <tr>
                        <td class="small">{{ u.man_number }}</td>
                        <td class="small">{{ u.user_name }}</td>
                        <td class="small">{{ u.bumon_cd.bumon_name|default:'' }}</td>
                        <td class="small">{{ u.post_cd.post_name|default:'' }}</td>
                        <td class="small">
                            {% for b in u.belongs.all %}{{ b.group_cd.group_name }}{% if not forloop.last %}, {% endif %}{% empty %}<span class="text-danger">（未所属）</span>{% endfor %}
                        </td>
                        <td class="text-center">
                            {% if u.is_active %}
                                <span class="badge bg-success">有効</span>
                            {% else %}
                                <span class="badge bg-secondary">無効</span>
                            {% endif %}
                        </td>
                        <td class="text-center">
                            <div class="d-flex gap-1 justify-content-center">
                                <a href="{% url 'expenses:settings_master_edit' 'm_user' u.pk %}"
                                   class="btn btn-outline-primary btn-sm py-0 px-2" title="編集">
                                    <i class="fas fa-edit"></i>
                                </a>
                                <button type="button"
                                        class="btn btn-sm py-0 px-2 js-toggle-active {% if u.is_active %}btn-outline-danger{% else %}btn-outline-success{% endif %}"
                                        data-url="{% url 'expenses:user_toggle_active' u.pk %}"
                                        data-user-name="{{ u.user_name }}"
                                        data-active="{% if u.is_active %}1{% else %}0{% endif %}">
                                    {% if u.is_active %}無効化{% else %}有効化{% endif %}
                                </button>
                            </div>
                        </td>
                    </tr>
                {% empty %}
                    <tr>
                        <td colspan="7" class="text-center text-muted py-4">条件に一致するユーザーがいません</td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ページネーション（フィルタ条件を引き継ぐ） -->
    {% if page_obj.has_other_pages %}
    <nav class="mt-3">
        <ul class="pagination pagination-sm justify-content-center mb-0">
            {% if page_obj.has_previous %}
                <li class="page-item">
                    <a class="page-link" href="?page={{ page_obj.previous_page_number }}{% if qstring %}&{{ qstring }}{% endif %}">前へ</a>
                </li>
            {% else %}
                <li class="page-item disabled"><span class="page-link">前へ</span></li>
            {% endif %}
            <li class="page-item disabled">
                <span class="page-link">{{ page_obj.number }} / {{ page_obj.paginator.num_pages }}</span>
            </li>
            {% if page_obj.has_next %}
                <li class="page-item">
                    <a class="page-link" href="?page={{ page_obj.next_page_number }}{% if qstring %}&{{ qstring }}{% endif %}">次へ</a>
                </li>
            {% else %}
                <li class="page-item disabled"><span class="page-link">次へ</span></li>
            {% endif %}
        </ul>
    </nav>
    {% endif %}
</div>

<script>
// 有効化/無効化トグル（Task 5 で追加する user_toggle_active API を呼ぶ）
document.querySelectorAll('.js-toggle-active').forEach(function (btn) {
    btn.addEventListener('click', function () {
        var action = btn.dataset.active === '1' ? '無効化' : '有効化';
        if (!confirm(btn.dataset.userName + ' さんを' + action + 'しますか？')) return;
        fetch(btn.dataset.url, {
            method: 'POST',
            headers: {'X-CSRFToken': '{{ csrf_token }}'},
        }).then(function (r) {
            if (!r.ok) {
                r.text().then(function (t) { alert(t || '更新に失敗しました。'); });
                return;
            }
            location.reload();
        }).catch(function () { alert('通信に失敗しました。'); });
    });
});
</script>
{% endblock %}
```

※ この時点では `user_toggle_active` のURLがまだ無いため、`{% url %}` が NoReverseMatch になる。**Step 6 のテストは Task 5 完了後に通る**——を避けるため、このTaskのテンプレートではトグルボタン部分も含めて書くが、**テスト実行は Task 5 の後にまとめて行わず、ここでは一時的に URL 追加も行う**（下記 Step 6）。

- [ ] **Step 6: トグルURLのプレースホルダを先に追加（NoReverseMatch回避）**

`expenses/urls.py` のマスタ設定ブロック（88行目 `settings/master/` の直前）に追加:

```python
    path("settings/master/m_user/<int:pk>/toggle_active/", views.user_toggle_active, name="user_toggle_active"),
```

`expenses/views_org_manager.py` の末尾に最小実装を追加（本実装・テストは Task 5）:

```python
@login_required
@require_POST
def user_toggle_active(request, pk):
    """ユーザーの有効/無効をトグル（AJAX POST）。自分自身は無効化不可。"""
    user = get_object_or_404(M_User, pk=pk)
    if user.pk == request.user.pk:
        return HttpResponseBadRequest('自分自身は無効化できません。')
    user.is_active = not user.is_active
    user.save(update_fields=['is_active'])
    return JsonResponse({'is_active': user.is_active})
```

`expenses/views.py` の import を最終形に更新:

```python
from .views_org_manager import (
    group_manager_list,
    user_manager_list,
    user_toggle_active,
)
```

- [ ] **Step 7: テストが通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_org_manager --keepdb -v 2"`
Expected: OK (13 tests)

- [ ] **Step 8: コミット**

```bash
wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && git add expenses/views_org_manager.py expenses/views.py expenses/urls.py expenses/templates/expenses/user_manager_list.html expenses/test_org_manager.py && git commit -m 'feat: ユーザーマスタ一覧をフィルタ検索画面に差し替え（所属部署列・有効無効トグル付き）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>'"
```

---

### Task 5: `user_toggle_active` のテスト補強（自己無効化ガード・POST限定）

**Files:**
- Modify: `expenses/views_org_manager.py`（Task 4 Step 6 の実装を検証、必要なら修正のみ）
- Test: `expenses/test_org_manager.py`

**Interfaces:**
- Consumes: `user_toggle_active`（Task 4 Step 6 で追加済み）
- Produces: 検証済みのトグルAPI。`POST /settings/master/m_user/<pk>/toggle_active/` → `{"is_active": bool}`。自分自身は 400。GET は 405。

- [ ] **Step 1: 失敗する（または既に通る）テストを書く**

`expenses/test_org_manager.py` に追記:

```python
class UserToggleActiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.login_user = User.objects.create_user(
            username='tester4', man_number='9005',
            user_name='テスト四郎', password='pass')
        cls.target = User.objects.create_user(
            username='target1', man_number='1003',
            user_name='対象五郎', password='pass', is_active=True)

    def _url(self, pk):
        return reverse('expenses:user_toggle_active', args=[pk])

    def test_POSTで有効無効がトグルしJSONが返る(self):
        self.client.force_login(self.login_user)
        res = self.client.post(self._url(self.target.pk))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()['is_active'])
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        # もう一度で戻る
        res = self.client.post(self._url(self.target.pk))
        self.assertTrue(res.json()['is_active'])

    def test_自分自身は無効化できない(self):
        self.client.force_login(self.login_user)
        res = self.client.post(self._url(self.login_user.pk))
        self.assertEqual(res.status_code, 400)
        self.login_user.refresh_from_db()
        self.assertTrue(self.login_user.is_active)

    def test_GETは405(self):
        self.client.force_login(self.login_user)
        res = self.client.get(self._url(self.target.pk))
        self.assertEqual(res.status_code, 405)
```

- [ ] **Step 2: テストを実行して結果を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_org_manager.UserToggleActiveTests --keepdb -v 2"`
Expected: OK (3 tests)（Task 4 Step 6 の実装が正しければ通る。失敗した場合のみ `user_toggle_active` を修正する）

- [ ] **Step 3: 全テストを実行**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_org_manager --keepdb -v 2"`
Expected: OK (16 tests)

- [ ] **Step 4: コミット**

```bash
wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && git add expenses/test_org_manager.py && git commit -m 'test: 有効無効トグルAPIのテストを追加（自己無効化ガード・POST限定）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>'"
```

---

### Task 6: リグレッション確認＋読み取り専用ランタイム確認

**Files:**
- なし（確認のみ。問題があれば該当Taskの修正としてコミット）

- [ ] **Step 1: 関連する既存テストがすべて通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_org_manager expenses.tests --keepdb -v 1"`
Expected: OK（失敗があれば該当Taskに戻って修正）

- [ ] **Step 2: Djangoチェック**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -c "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py check"`
Expected: `System check identified no issues`

- [ ] **Step 3: 読み取り専用ランタイム確認（verifyスキルの手順に従う）**

`verify` スキルを起動し、その手順に従って開発サーバーで以下を目視確認する（**本番DB直結のため参照のみ。編集・削除・トグルボタンは押さない**）:
- `/settings/master/m_group/` — ツリーがインデント表示される・人数バッジクリックで所属ユーザーが展開される・「上位不明」バッジが出るデータがないか確認
- `/settings/master/m_user/` — デフォルトで有効のみ表示・各フィルタとキーワード検索が機能する・所属部署列と（未所属）表示・ページネーションでフィルタ条件が引き継がれる
- `/settings/master/m_bumon/` など他マスタが従来通り表示される

- [ ] **Step 4: 確認結果を報告**

テスト結果・ランタイム確認結果（スクリーンショット可能なら添えて）をユーザーに報告する。
