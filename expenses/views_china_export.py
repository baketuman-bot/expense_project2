"""各部報告: 中国輸出実績報告 (T_ChinaExport) の一覧・入力・CSV出力ビュー"""
import csv as csv_module

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import ChinaExportUpdateForm
from .models import T_ChinaExport


def _require_china_export_access(user):
    if not (user.has_role('export') or user.has_role('admin')):
        raise PermissionDenied()


def _china_export_queryset(show_all):
    records = T_ChinaExport.objects.order_by('purchase_date', 'pk')
    if not show_all:
        records = records.filter(export_date__isnull=True)
    return records


@login_required
def china_export_list(request):
    _require_china_export_access(request.user)
    show_all = request.GET.get('show') == 'all'
    return render(request, 'expenses/china_export_list.html', {
        'records': _china_export_queryset(show_all),
        'show_all': show_all,
        'current': 'china_export_list',
    })


_CSV_HEADERS = [
    '状態', '注文番号', '仕入先コード', '仕入先名', '品目コード', '品目名1', '品目名2',
    '仕入単価', '購入日', '数量', '金額', '科目コード', '科目名',
    '負担部門コード', '負担部署名', '発注部署名', '発注担当名',
    '輸出予定日', '輸出日', 'インボイスNo',
]


def _china_export_to_row(r):
    def d(v):
        return v.strftime('%Y/%m/%d') if v else ''

    def n(v):
        return str(v) if v is not None else ''

    return [
        '輸出済' if r.export_date else '未輸出',
        r.order_no or '',
        r.supplier_cd or '',
        r.supplier_name or '',
        r.item_cd or '',
        r.item_name1,
        r.item_name2 or '',
        n(r.unit_price),
        d(r.purchase_date),
        n(r.quantity),
        n(r.amount),
        r.account_cd or '',
        r.account_name or '',
        r.burden_bumon_cd or '',
        r.burden_bumon_name or '',
        r.order_bumon_name or '',
        r.order_staff_name or '',
        d(r.export_planned_date),
        d(r.export_date),
        r.invoice_no or '',
    ]


@login_required
def china_export_csv(request):
    _require_china_export_access(request.user)
    show_all = request.GET.get('show') == 'all'
    records = _china_export_queryset(show_all)

    class EchoBuffer:
        def write(self, value):
            return value

    writer = csv_module.writer(EchoBuffer())

    def rows():
        yield writer.writerow(_CSV_HEADERS)
        for r in records.iterator():
            yield writer.writerow(_china_export_to_row(r))

    response = StreamingHttpResponse(rows(), content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="china_export.csv"'
    return response


@login_required
@require_POST
def china_export_update(request, pk):
    _require_china_export_access(request.user)
    record = get_object_or_404(T_ChinaExport, pk=pk)
    form = ChinaExportUpdateForm(request.POST, instance=record)
    if form.is_valid():
        updated = form.save(commit=False)
        updated.updated_by = request.user
        updated.save(update_fields=[
            'export_planned_date', 'export_date', 'invoice_no',
            'updated_by', 'updated_at',
        ])
    base_url = reverse('expenses:china_export_list')
    if request.POST.get('show') == 'all':
        return redirect(f'{base_url}?show=all')
    return redirect(base_url)
