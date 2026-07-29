# 中国輸出実績報告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 経理が直接DBへ投入する中国輸出関連の購入データに対し、`export` ロールを持つ担当社員が輸出予定日・輸出日・インボイスNoを入力してフォローできる一覧画面を、新設のサイドバーセクション「各部報告」から提供する。

**Architecture:** 新規テーブル `T_ChinaExport` を追加し、専用ビューファイル `expenses/views_china_export.py`（一覧GET・更新POSTの2ビュー）とカード形式テンプレート1枚で完結させる。権限は既存の `M_UserRole` / `has_role()` をそのまま利用し、新しいロール文字列 `'export'` を条件に使う。既存の `固定資産` セクションと同じ構造（`context_processors.py` でフラグ算出→`base.html` で条件表示）をサイドバーに追加する。

**Tech Stack:** Django 5.2.6 / Python 3.12（`.venv`）/ MySQL 8.0 / Bootstrap 5 + `swiss.css`

## Global Constraints

- 設計書: `docs/superpowers/specs/2026-07-29-china-export-report-design.md`（このPlanは同ファイルの決定事項に従う）
- 本番DB (`expense_db`) を直接使う開発。**破壊的操作（DELETE/TRUNCATE/DROP/flush）は一切行わない**。マイグレーションは `CreateModel` のみ（非破壊的）
- テスト実行は必ず `--keepdb` 付きで `test_expense_db` を使う。`DJANGO_TEST_DB_NAME=expense_db` は絶対に設定しない
- コマンド実行は Windows の Bash ツールから WSL 内 Python を直接呼べないため、`wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python ..."` の形式を使う
- モデルのNULL制約: `item_name1`（品目名1）と `amount`（金額）のみ NOT NULL。他の経理入力項目・輸出関連3項目はすべてNULL許容
- 一覧のデフォルトフィルタは `export_date__isnull=True`、並び順は `purchase_date` 昇順、検索・絞り込みは実装しない
- 編集可能項目は `export_planned_date` / `export_date` / `invoice_no` の3つのみ。経理入力項目はPOSTされても更新されないこと
- 権限は新規ロール文字列 `'export'`（管理者バイパスなし。設計通り厳密にロール保持者のみ許可）

---

### Task 1: T_ChinaExportモデルとマイグレーション

**Files:**
- Modify: `expenses/models.py`（末尾、`GS_Position` クラスの後に追加）
- Create: `expenses/migrations/0116_t_china_export.py`（`makemigrations` で自動生成）
- Create: `expenses/test_china_export.py`

**Interfaces:**
- Produces: `T_ChinaExport` モデル（`expenses.models.T_ChinaExport`）。フィールド: `order_no, supplier_cd, supplier_name, item_cd, item_name1, item_name2, unit_price, purchase_date, quantity, amount, account_cd, account_name, burden_bumon_cd, burden_bumon_name, order_bumon_name, order_staff_name, export_planned_date, export_date, invoice_no, updated_by, updated_at`。`item_name1`・`amount` のみ必須（NOT NULL）、他はすべてNULL許容。`db_table='t_china_export'`

- [ ] **Step 1: 失敗するモデルテストを書く**

`expenses/test_china_export.py` を新規作成:

```python
"""中国輸出実績報告 (T_ChinaExport) のテスト"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from expenses.models import M_UserRole, T_ChinaExport

User = get_user_model()


class TChinaExportModelTests(TestCase):
    def test_品目名1がNullだと保存時にエラー(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                T_ChinaExport.objects.create(item_name1=None, amount=Decimal('100.00'))

    def test_金額がNullだと保存時にエラー(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                T_ChinaExport.objects.create(item_name1='テスト品目', amount=None)

    def test_品目名1と金額以外はNullで保存できる(self):
        record = T_ChinaExport.objects.create(
            item_name1='テスト品目', amount=Decimal('1000.00'))
        self.assertIsNone(record.order_no)
        self.assertIsNone(record.purchase_date)
        self.assertIsNone(record.export_planned_date)
        self.assertIsNone(record.export_date)
        self.assertIsNone(record.invoice_no)
        self.assertIsNone(record.updated_by)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_export --keepdb -v 2"
```
Expected: `ImportError: cannot import name 'T_ChinaExport'`（モデル未定義のため）

- [ ] **Step 3: モデルを実装**

`expenses/models.py` の末尾（`class GS_Position` の定義の後）に追加:

```python
class T_ChinaExport(models.Model):
    """中国輸出実績報告: 経理が輸出目的の購入データを直接投入し、
    担当社員が輸出予定日・輸出日・インボイスNoを入力してフォローする。"""

    order_no = models.CharField("注文番号", max_length=15, null=True, blank=True)
    supplier_cd = models.CharField("仕入先コード", max_length=10, null=True, blank=True)
    supplier_name = models.CharField("仕入先名", max_length=30, null=True, blank=True)
    item_cd = models.CharField("品目コード", max_length=15, null=True, blank=True)
    item_name1 = models.CharField("品目名1", max_length=50)
    item_name2 = models.CharField("品目名2", max_length=50, null=True, blank=True)
    unit_price = models.DecimalField("仕入単価", max_digits=10, decimal_places=5, null=True, blank=True)
    purchase_date = models.DateField("購入日", null=True, blank=True)
    quantity = models.DecimalField("数量", max_digits=10, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField("金額", max_digits=10, decimal_places=2)
    account_cd = models.CharField("科目コード", max_length=10, null=True, blank=True)
    account_name = models.CharField("科目名", max_length=30, null=True, blank=True)
    burden_bumon_cd = models.CharField("負担部門コード", max_length=10, null=True, blank=True)
    burden_bumon_name = models.CharField("負担部署名", max_length=20, null=True, blank=True)
    order_bumon_name = models.CharField("発注部署名", max_length=20, null=True, blank=True)
    order_staff_name = models.CharField("発注担当名", max_length=20, null=True, blank=True)

    export_planned_date = models.DateField("輸出予定日", null=True, blank=True)
    export_date = models.DateField("輸出日", null=True, blank=True)
    invoice_no = models.CharField("インボイスNo", max_length=30, null=True, blank=True)

    updated_by = models.ForeignKey(
        M_User, verbose_name="最終更新者", null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    updated_at = models.DateTimeField("最終更新日時", auto_now=True)

    def __str__(self):
        return f"{self.order_no or '(注文番号未設定)'} {self.item_name1}"

    class Meta:
        db_table = 't_china_export'
        verbose_name = '中国輸出実績報告'
        verbose_name_plural = '中国輸出実績報告'
```

- [ ] **Step 4: マイグレーションを生成**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py makemigrations expenses"
```
Expected: `expenses/migrations/0116_t_china_export.py` が生成され、`Create model T_ChinaExport` の1操作のみを含むこと（生成内容を確認する）

- [ ] **Step 5: テストを再実行して成功を確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_export --keepdb -v 2"
```
Expected: `TChinaExportModelTests` の3件がすべてPASS（`--keepdb` により `test_expense_db` にマイグレーションが自動適用される）

- [ ] **Step 6: コミット**

```bash
git add expenses/models.py expenses/migrations/0116_t_china_export.py expenses/test_china_export.py
git commit -m "feat: 中国輸出実績報告用のT_ChinaExportモデルを追加"
```

---

### Task 2: フォーム・ビュー・URL・一覧テンプレート

**Files:**
- Modify: `expenses/forms.py`（import行と末尾に `ChinaExportUpdateForm` を追加）
- Create: `expenses/views_china_export.py`
- Modify: `expenses/views.py`（`views_china_export` からのre-export追加）
- Modify: `expenses/urls.py`（`china_export_list` / `china_export_update` のURL追加）
- Create: `expenses/templates/expenses/china_export_list.html`
- Modify: `expenses/test_china_export.py`（一覧・更新のビューテストを追加）

**Interfaces:**
- Consumes: Task 1 の `T_ChinaExport`（フィールド名は Task 1 と同一）
- Produces: `expenses:china_export_list`（GET、コンテキスト `records`, `show_all`）、`expenses:china_export_update`（POST、`pk` 引数）。テンプレートで使うフィールド名はモデルと同一

- [ ] **Step 1: 失敗するビューテストを書く**

`expenses/test_china_export.py` の末尾に追加:

```python
class ChinaExportListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.export_user = User.objects.create_user(
            username='export_tester', man_number='9101',
            user_name='輸出担当', password='pass')
        M_UserRole.objects.create(man_number=cls.export_user, role='export')

        cls.other_user = User.objects.create_user(
            username='other_tester', man_number='9102',
            user_name='権限なし', password='pass')

        cls.unexported = T_ChinaExport.objects.create(
            item_name1='未輸出品', amount=Decimal('5000.00'),
            purchase_date=date(2026, 6, 1))
        cls.exported = T_ChinaExport.objects.create(
            item_name1='輸出済品', amount=Decimal('3000.00'),
            purchase_date=date(2026, 5, 1),
            export_date=date(2026, 6, 15))

    def test_exportロールを持たないユーザーは403(self):
        self.client.force_login(self.other_user)
        res = self.client.get(reverse('expenses:china_export_list'))
        self.assertEqual(res.status_code, 403)

    def test_デフォルトは未輸出のみ表示(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '未輸出品')
        self.assertNotContains(res, '輸出済品')

    def test_show_allで全件表示(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_list') + '?show=all')
        self.assertContains(res, '未輸出品')
        self.assertContains(res, '輸出済品')

    def test_購入日昇順で並ぶ(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_list') + '?show=all')
        records = list(res.context['records'])
        self.assertEqual(
            [r.pk for r in records],
            [self.exported.pk, self.unexported.pk])


class ChinaExportUpdateViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.export_user = User.objects.create_user(
            username='export_tester2', man_number='9103',
            user_name='輸出担当2', password='pass')
        M_UserRole.objects.create(man_number=cls.export_user, role='export')
        cls.other_user = User.objects.create_user(
            username='other_tester2', man_number='9104',
            user_name='権限なし2', password='pass')
        cls.record = T_ChinaExport.objects.create(
            order_no='ORDER0001', item_name1='対象品目', amount=Decimal('1234.00'))

    def test_exportロールを持たないユーザーは更新不可(self):
        self.client.force_login(self.other_user)
        res = self.client.post(
            reverse('expenses:china_export_update', args=[self.record.pk]),
            {'export_planned_date': '2026-08-01', 'export_date': '', 'invoice_no': 'INV-001'})
        self.assertEqual(res.status_code, 403)

    def test_輸出予定日と輸出日とインボイスNoが保存されupdated_byが記録される(self):
        self.client.force_login(self.export_user)
        res = self.client.post(
            reverse('expenses:china_export_update', args=[self.record.pk]),
            {'export_planned_date': '2026-08-01', 'export_date': '2026-08-10', 'invoice_no': 'INV-001'})
        self.assertRedirects(res, reverse('expenses:china_export_list'))
        self.record.refresh_from_db()
        self.assertEqual(self.record.export_planned_date, date(2026, 8, 1))
        self.assertEqual(self.record.export_date, date(2026, 8, 10))
        self.assertEqual(self.record.invoice_no, 'INV-001')
        self.assertEqual(self.record.updated_by, self.export_user)

    def test_経理入力項目はPOSTに含めても更新されない(self):
        self.client.force_login(self.export_user)
        self.client.post(
            reverse('expenses:china_export_update', args=[self.record.pk]),
            {
                'export_planned_date': '', 'export_date': '', 'invoice_no': '',
                'order_no': 'HACKED', 'amount': '999999.00',
            })
        self.record.refresh_from_db()
        self.assertEqual(self.record.order_no, 'ORDER0001')
        self.assertEqual(self.record.amount, Decimal('1234.00'))

    def test_show_allを維持したままリダイレクトされる(self):
        self.client.force_login(self.export_user)
        res = self.client.post(
            reverse('expenses:china_export_update', args=[self.record.pk]),
            {'export_planned_date': '', 'export_date': '', 'invoice_no': '', 'show': 'all'})
        self.assertRedirects(res, reverse('expenses:china_export_list') + '?show=all')
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_export --keepdb -v 2"
```
Expected: `NoReverseMatch`（`expenses:china_export_list` が未定義のため）

- [ ] **Step 3: フォームを実装**

`expenses/forms.py` の3行目のimportに `T_ChinaExport` を追加:

```python
from .models import T_Document, T_DocumentContent, M_Account, M_Item, T_Assets, M_User, M_Group, M_BelongTo, T_ChinaExport
```

ファイル末尾に追加:

```python
class ChinaExportUpdateForm(forms.ModelForm):
    class Meta:
        model = T_ChinaExport
        fields = ['export_planned_date', 'export_date', 'invoice_no']
        widgets = {
            'export_planned_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
            'export_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
            'invoice_no': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'maxlength': 30}),
        }
```

- [ ] **Step 4: ビューを実装**

`expenses/views_china_export.py` を新規作成:

```python
"""各部報告: 中国輸出実績報告 (T_ChinaExport) の一覧・入力ビュー"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import ChinaExportUpdateForm
from .models import T_ChinaExport


@login_required
def china_export_list(request):
    if not request.user.has_role('export'):
        raise PermissionDenied()
    show_all = request.GET.get('show') == 'all'
    records = T_ChinaExport.objects.order_by('purchase_date', 'pk')
    if not show_all:
        records = records.filter(export_date__isnull=True)
    return render(request, 'expenses/china_export_list.html', {
        'records': records,
        'show_all': show_all,
    })


@login_required
@require_POST
def china_export_update(request, pk):
    if not request.user.has_role('export'):
        raise PermissionDenied()
    record = get_object_or_404(T_ChinaExport, pk=pk)
    form = ChinaExportUpdateForm(request.POST, instance=record)
    if form.is_valid():
        updated = form.save(commit=False)
        updated.updated_by = request.user
        updated.save()
    base_url = reverse('expenses:china_export_list')
    if request.POST.get('show') == 'all':
        return redirect(f'{base_url}?show=all')
    return redirect(base_url)
```

- [ ] **Step 5: views.py で re-export**

`expenses/views.py` の `from .views_org_manager import (...)` ブロックの直後に追加:

```python
from .views_china_export import (
    china_export_list,
    china_export_update,
)  # noqa: F401
```

- [ ] **Step 6: URLを配線**

`expenses/urls.py` の `# 改善要望` ブロック（`feedback_delete` の行）の直後に追加:

```python
    # 各部報告: 中国輸出実績報告
    path("china_export/", views.china_export_list, name="china_export_list"),
    path("china_export/<int:pk>/update/", views.china_export_update, name="china_export_update"),
```

- [ ] **Step 7: 一覧テンプレートを作成**

`expenses/templates/expenses/china_export_list.html` を新規作成:

```html
{% extends "expenses/base.html" %}
{% load expense_extras %}

{% block title %}中国輸出実績報告 | {% endblock %}

{% block content %}
<div class="mt-2">

    <div class="page-head mb-3">
        <h2 class="page-title mb-0">
            <span class="pt-ico"><i class="fas fa-ship"></i></span>
            中国輸出実績報告
        </h2>
        <div class="page-actions">
            {% if show_all %}
            <a href="{% url 'expenses:china_export_list' %}" class="btn btn-outline-secondary btn-sm">未輸出のみ表示</a>
            {% else %}
            <a href="{% url 'expenses:china_export_list' %}?show=all" class="btn btn-outline-secondary btn-sm">全件表示</a>
            {% endif %}
        </div>
    </div>

    <p class="text-muted small mb-3">
        {% if show_all %}全件表示中（{{ records|length }}件）{% else %}未輸出のみ表示中（{{ records|length }}件）{% endif %}
    </p>

    {% if records %}
    <div class="row g-3">
        {% for record in records %}
        <div class="col-12 col-lg-6">
            <div class="card h-100">
                <div class="card-header bg-light d-flex justify-content-between align-items-center">
                    <span class="fw-bold">{{ record.order_no|default:"（注文番号未設定）" }}</span>
                    {% if record.export_date %}
                    <span class="status-pill status-pill-approved">輸出済</span>
                    {% else %}
                    <span class="status-pill status-pill-pending">未輸出</span>
                    {% endif %}
                </div>
                <div class="card-body">
                    <dl class="row small mb-3">
                        <dt class="col-5">仕入先</dt><dd class="col-7">{{ record.supplier_name|default:"-" }}（{{ record.supplier_cd|default:"-" }}）</dd>
                        <dt class="col-5">品目コード</dt><dd class="col-7">{{ record.item_cd|default:"-" }}</dd>
                        <dt class="col-5">品目名1</dt><dd class="col-7">{{ record.item_name1 }}</dd>
                        <dt class="col-5">品目名2</dt><dd class="col-7">{{ record.item_name2|default:"-" }}</dd>
                        <dt class="col-5">仕入単価</dt><dd class="col-7">{{ record.unit_price|default:"-" }}</dd>
                        <dt class="col-5">購入日</dt><dd class="col-7">{{ record.purchase_date|date:"Y/m/d"|default:"-" }}</dd>
                        <dt class="col-5">数量</dt><dd class="col-7">{{ record.quantity|default:"-" }}</dd>
                        <dt class="col-5">金額</dt><dd class="col-7">{{ record.amount }}</dd>
                        <dt class="col-5">科目</dt><dd class="col-7">{{ record.account_name|default:"-" }}（{{ record.account_cd|default:"-" }}）</dd>
                        <dt class="col-5">負担部門</dt><dd class="col-7">{{ record.burden_bumon_name|default:"-" }}（{{ record.burden_bumon_cd|default:"-" }}）</dd>
                        <dt class="col-5">発注部署</dt><dd class="col-7">{{ record.order_bumon_name|default:"-" }}</dd>
                        <dt class="col-5">発注担当</dt><dd class="col-7">{{ record.order_staff_name|default:"-" }}</dd>
                    </dl>
                    <form method="post" action="{% url 'expenses:china_export_update' record.pk %}">
                        {% csrf_token %}
                        <input type="hidden" name="show" value="{% if show_all %}all{% endif %}">
                        <div class="row g-2 align-items-end">
                            <div class="col-6 col-md-4">
                                <label class="form-label small mb-1">輸出予定日</label>
                                <input type="date" name="export_planned_date" class="form-control form-control-sm" value="{{ record.export_planned_date|date:'Y-m-d' }}">
                            </div>
                            <div class="col-6 col-md-4">
                                <label class="form-label small mb-1">輸出日</label>
                                <input type="date" name="export_date" class="form-control form-control-sm" value="{{ record.export_date|date:'Y-m-d' }}">
                            </div>
                            <div class="col-8 col-md-3">
                                <label class="form-label small mb-1">インボイスNo</label>
                                <input type="text" name="invoice_no" class="form-control form-control-sm" value="{{ record.invoice_no|default:'' }}" maxlength="30">
                            </div>
                            <div class="col-4 col-md-1">
                                <button type="submit" class="btn btn-primary btn-sm w-100">保存</button>
                            </div>
                        </div>
                    </form>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div class="text-center py-5">
        <i class="fas fa-ship fa-4x text-muted mb-3 d-block"></i>
        <h4 class="text-muted">{% if show_all %}データがありません{% else %}未輸出のデータはありません{% endif %}</h4>
    </div>
    {% endif %}

</div>
{% endblock %}
```

- [ ] **Step 8: テストを再実行して成功を確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_export --keepdb -v 2"
```
Expected: `ChinaExportListViewTests`・`ChinaExportUpdateViewTests` を含む全テストがPASS

- [ ] **Step 9: コミット**

```bash
git add expenses/forms.py expenses/views_china_export.py expenses/views.py expenses/urls.py expenses/templates/expenses/china_export_list.html expenses/test_china_export.py
git commit -m "feat: 中国輸出実績報告の一覧・入力ビューを追加"
```

---

### Task 3: サイドバー表示（各部報告セクション）

**Files:**
- Modify: `expenses/context_processors.py`（`can_view_china_export` フラグを追加）
- Modify: `expenses/templates/expenses/base.html`（「各部報告」セクション追加）
- Modify: `expenses/test_china_export.py`（サイドバー表示のテストを追加）

**Interfaces:**
- Consumes: Task 2 の `expenses:china_export_list` URL名
- Produces: テンプレートコンテキスト変数 `can_view_china_export`（bool）。`base.html` はこれで新セクションの表示可否を判定する

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_export.py` の末尾に追加:

```python
class ChinaExportSidebarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.export_user = User.objects.create_user(
            username='export_tester3', man_number='9105',
            user_name='輸出担当3', password='pass')
        M_UserRole.objects.create(man_number=cls.export_user, role='export')
        cls.other_user = User.objects.create_user(
            username='other_tester3', man_number='9106',
            user_name='権限なし3', password='pass')

    def test_exportロール保持者はサイドバーにメニューが出る(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:home'))
        self.assertContains(res, '中国輸出実績報告')

    def test_exportロールがないユーザーには出ない(self):
        self.client.force_login(self.other_user)
        res = self.client.get(reverse('expenses:home'))
        self.assertNotContains(res, '中国輸出実績報告')
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_export.ChinaExportSidebarTests --keepdb -v 2"
```
Expected: `test_exportロール保持者はサイドバーにメニューが出る` がFAIL（「中国輸出実績報告」の文字列がまだどこにも出力されないため）

- [ ] **Step 3: context_processors.py にフラグを追加**

`expenses/context_processors.py` の末尾（`can_manage_assets` の算出ブロックと `return` 文）は現状こうなっている:

```python
    can_manage_assets = False
    try:
        can_manage_assets = request.user.has_role('accountant') or request.user.has_role('admin')
    except Exception:
        pass

    return {
        'sidebar_expense_groups': sidebar_groups,
        'pending_approval_count': pending_approval_count,
        'settlement_pending_count': settlement_pending_count,
        'can_manage_assets': can_manage_assets,
    }
```

これを次のように書き換える（`can_view_china_export` の算出を追加し、`return` 辞書にキーを追加する）:

```python
    can_manage_assets = False
    try:
        can_manage_assets = request.user.has_role('accountant') or request.user.has_role('admin')
    except Exception:
        pass

    can_view_china_export = False
    try:
        can_view_china_export = request.user.has_role('export')
    except Exception:
        pass

    return {
        'sidebar_expense_groups': sidebar_groups,
        'pending_approval_count': pending_approval_count,
        'settlement_pending_count': settlement_pending_count,
        'can_manage_assets': can_manage_assets,
        'can_view_china_export': can_view_china_export,
    }
```

- [ ] **Step 4: base.html にセクションを追加**

`expenses/templates/expenses/base.html` には「固定資産」セクションの直後にこの並びがある（`{% if can_manage_assets %}` の `MDB同期について` リンクで固定資産セクションが終わり、その直後に `precision-user` ブロックが始まる）:

```html
                {% if can_manage_assets %}
                <li>
                    <a class="precision-link {% if current == 'assets_sync_info' %}is-active{% endif %}" href="{% url 'expenses:assets_sync_info' %}">
                        <span class="precision-ico" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M21 12a9 9 0 0 1-15.3 6.5L3 21"></path>
                                <path d="M3 12a9 9 0 0 1 15.3-6.5L21 3"></path>
                                <path d="M3 21v-4h4"></path>
                                <path d="M21 3v4h-4"></path>
                            </svg>
                        </span>
                        <span>MDB同期について</span>
                    </a>
                </li>
                {% endif %}
            </ul>
        </div>

        <div class="precision-user">
```

`</div>`（固定資産セクションを閉じるタグ）の直後・`<div class="precision-user">` の直前に、新しい「各部報告」セクションを挿入する。編集後は次の並びになる:

```html
        {% if can_view_china_export %}
        <div class="precision-section">
            <div class="precision-section-label">各部報告</div>
            <ul class="precision-nav">
                <li>
                    <a class="precision-link {% if current == 'china_export_list' %}is-active{% endif %}" href="{% url 'expenses:china_export_list' %}">
                        <span class="precision-ico" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M2 12s2-7 10-7 10 7 10 7-2 7-10 7-10-7-10-7Z"></path>
                                <path d="M12 8v8"></path>
                                <path d="M8 12h8"></path>
                            </svg>
                        </span>
                        <span>中国輸出実績報告</span>
                    </a>
                </li>
            </ul>
        </div>
        {% endif %}
```

- [ ] **Step 5: テストを再実行して成功を確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_export --keepdb -v 2"
```
Expected: `test_china_export.py` の全テストがPASS

- [ ] **Step 6: コミット**

```bash
git add expenses/context_processors.py expenses/templates/expenses/base.html expenses/test_china_export.py
git commit -m "feat: 各部報告セクション(中国輸出実績報告)をサイドバーに追加"
```

---

### Task 4: 本番DBへのマイグレーション適用と読み取り専用の動作確認

**Files:**
- なし（コード変更なし。本番DBスキーマ変更と確認のみ）

**Interfaces:**
- Consumes: Task 1〜3で作成した全ファイル

- [ ] **Step 1: 全テストを最終確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_export --keepdb -v 2"
```
Expected: 全テストPASS

- [ ] **Step 2: システムチェック**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py check"
```
Expected: `System check identified no issues`

- [ ] **Step 3: 本番DBへマイグレーション適用**

`0116_t_china_export.py` は `CreateModel` のみ（新規テーブル追加、既存データに影響しない非破壊的操作）。本番DB (`expense_db`) に適用する:

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py migrate expenses 0116"
```
Expected: `Applying expenses.0116_t_china_export... OK`

- [ ] **Step 4: 新規テーブルのコレーションを確認**

CLAUDE.md の規約に従い、新規作成した `t_china_export` テーブルのコレーションが統一ルール `utf8mb4_0900_ai_ci` になっているか読み取り専用で確認する（DB既定が2026-07-17に統一済みのため一致するはずだが、必ず確認する）:

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py shell -c \"from django.db import connection; c = connection.cursor(); c.execute(\\\"SELECT TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='t_china_export'\\\"); print(c.fetchone())\""
```
Expected: `('utf8mb4_0900_ai_ci',)`。異なる場合はこのタスクを完了とせず、`CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci` を実行するマイグレーションを追加してから再度確認する

- [ ] **Step 5: URL解決とロールゲートを読み取り専用で確認**

本番ユーザーに `export` ロールはまだ誰も付与されていない想定のため、実データ投入や実ユーザーへのロール付与は行わず、`RequestFactory` でロール未保持ユーザーに対して `PermissionDenied` が正しく発生することのみを確認する（DB書込なし）:

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py shell -c \"
from django.test import RequestFactory
from django.core.exceptions import PermissionDenied
from expenses import views
from expenses.models import M_User
rf = RequestFactory()
req = rf.get('/china_export/')
req.user = M_User.objects.filter(is_active=True).first()
try:
    views.china_export_list(req)
    print('NG: PermissionDeniedが発生しなかった')
except PermissionDenied:
    print('OK: ロール未保持ユーザーは403')
\""
```
Expected: `OK: ロール未保持ユーザーは403`

- [ ] **Step 6: コミット**

このタスクはコード変更を伴わないため、コミット対象なし。実行結果を確認して完了とする。

---

## 運用メモ（実装完了後、ユーザーへの申し送り事項）

- `export` ロールをまだ誰にも付与していない。担当社員には `M_UserRole` に `role='export'` の行を追加する必要がある（既存の「マスタ設定」画面または直接DB操作）
- 経理担当者へ `T_ChinaExport`（テーブル名 `t_china_export`）のカラム定義を共有し、直接INSERTしてもらう運用を開始する
