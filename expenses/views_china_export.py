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
    if not (request.user.has_role('export') or request.user.has_role('admin')):
        raise PermissionDenied()
    show_all = request.GET.get('show') == 'all'
    records = T_ChinaExport.objects.order_by('purchase_date', 'pk')
    if not show_all:
        records = records.filter(export_date__isnull=True)
    return render(request, 'expenses/china_export_list.html', {
        'records': records,
        'show_all': show_all,
        'current': 'china_export_list',
    })


@login_required
@require_POST
def china_export_update(request, pk):
    if not (request.user.has_role('export') or request.user.has_role('admin')):
        raise PermissionDenied()
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
