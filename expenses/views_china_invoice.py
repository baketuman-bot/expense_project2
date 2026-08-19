"""中国輸出Invoice管理: Invoice登録・一覧・確認・月締め・Excel出力のビュー。
既存の中国輸出実績報告(T_ChinaExport)とは独立したサブシステム。"""
import datetime
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .china_invoice_files import validate_china_invoice_file
from .china_invoice_pdf import extract_invoice_fields
from .forms import ChinaInvoiceForm
from .models import T_ChinaInvoice, T_ChinaInvoiceMonthClose, T_ChinaInvoicePackingList

logger = logging.getLogger(__name__)


def _require_role(user, *roles):
    if user.has_role('admin'):
        return
    if any(user.has_role(r) for r in roles):
        return
    raise PermissionDenied()


def _is_month_closed(target_date):
    return T_ChinaInvoiceMonthClose.objects.filter(year_month=target_date.strftime('%Y-%m')).exists()


def _handle_packing_list_uploads(request, invoice, field_name='packing_list_files'):
    for f in request.FILES.getlist(field_name):
        validate_china_invoice_file(f)
        T_ChinaInvoicePackingList.objects.create(invoice=invoice, file=f, uploaded_by=request.user)


@login_required
def china_invoice_create(request):
    _require_role(request.user, 'china_reporter')

    if request.method == 'POST':
        form = ChinaInvoiceForm(request.POST, request.FILES)
        if not form.is_valid():
            uploaded = request.FILES.get('invoice_file')
            prefill = None
            if uploaded and (not form.data.get('invoice_no') or not form.data.get('invoice_total')):
                uploaded.seek(0)
                prefill = extract_invoice_fields(uploaded.read())
                uploaded.seek(0)
            return render(request, 'expenses/china_invoice_form.html', {
                'form': form, 'current': 'china_invoice_list', 'mode': 'create', 'prefill': prefill,
            })

        today = datetime.date.today()
        if _is_month_closed(today):
            form.add_error(None, '今月は月締め済みのため新規登録できません。')
            return render(request, 'expenses/china_invoice_form.html', {
                'form': form, 'current': 'china_invoice_list', 'mode': 'create',
            })

        instance = form.save(commit=False)
        instance.reporter = request.user
        instance.save()
        _handle_packing_list_uploads(request, instance)

        if instance.export_date.strftime('%Y-%m') != today.strftime('%Y-%m'):
            messages.warning(
                request,
                f'{instance.management_no}: 登録月（{today.strftime("%Y-%m")}）と輸出月'
                f'（{instance.export_date.strftime("%Y-%m")}）が異なります。')
        messages.success(request, f'{instance.management_no} を登録しました。')
        return redirect('expenses:china_invoice_detail', pk=instance.pk)

    form = ChinaInvoiceForm()
    return render(request, 'expenses/china_invoice_form.html', {
        'form': form, 'current': 'china_invoice_list', 'mode': 'create',
    })
