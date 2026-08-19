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
from django.views.decorators.http import require_POST

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


_LIST_ROLES = ('china_reporter', 'accountant', 'china_partner')


def _china_invoice_queryset(request):
    qs = T_ChinaInvoice.objects.select_related('cargo_category', 'reporter').order_by('-registered_at')
    params = request.GET
    if params.get('management_no'):
        qs = qs.filter(management_no__icontains=params['management_no'])
    if params.get('invoice_no'):
        qs = qs.filter(invoice_no__icontains=params['invoice_no'])
    if params.get('export_date'):
        qs = qs.filter(export_date=params['export_date'])
    if params.get('registered_date'):
        qs = qs.filter(registered_at__date=params['registered_date'])
    if params.get('cargo_category'):
        qs = qs.filter(cargo_category_id=params['cargo_category'])
    if params.get('reporter'):
        qs = qs.filter(reporter_id=params['reporter'])
    if params.get('invoice_total'):
        qs = qs.filter(invoice_total=params['invoice_total'])
    if params.get('accounting_confirmed') in ('0', '1'):
        qs = qs.filter(accounting_confirmed=(params['accounting_confirmed'] == '1'))
    if params.get('china_confirm_status'):
        qs = qs.filter(china_confirm_status=params['china_confirm_status'])
    if params.get('month_status') in ('closed', 'open'):
        closed_months = set(T_ChinaInvoiceMonthClose.objects.values_list('year_month', flat=True))
        ids = [
            r.pk for r in qs
            if (r.registered_at.strftime('%Y-%m') in closed_months) == (params['month_status'] == 'closed')
        ]
        qs = qs.filter(pk__in=ids)
    return qs


@login_required
def china_invoice_list(request):
    _require_role(request.user, *_LIST_ROLES)
    return render(request, 'expenses/china_invoice_list.html', {
        'records': _china_invoice_queryset(request),
        'current': 'china_invoice_list',
    })


_KEY_FIELDS = ['invoice_no', 'invoice_total', 'export_date', 'cargo_category_id', 'adjustment_rate_value']


def _can_edit(user, invoice):
    if user.has_role('admin') or user.has_role('accountant'):
        return True
    if user.has_role('china_reporter') and invoice.reporter_id == user.pk and not invoice.accounting_confirmed:
        return True
    return False


def _reset_confirmations_if_key_changed(old_snapshot, new_instance):
    changed = any(old_snapshot[f] != getattr(new_instance, f) for f in _KEY_FIELDS)
    if changed:
        new_instance.accounting_confirmed = False
        new_instance.accounting_confirmed_by = None
        new_instance.accounting_confirmed_at = None
        new_instance.china_confirm_status = T_ChinaInvoice.CHINA_STATUS_UNCONFIRMED
        new_instance.china_confirmed_by = None
        new_instance.china_confirmed_at = None
    return changed


@login_required
def china_invoice_detail(request, pk):
    _require_role(request.user, *_LIST_ROLES)
    invoice = get_object_or_404(
        T_ChinaInvoice.objects.select_related('cargo_category', 'reporter'), pk=pk)
    can_edit = _can_edit(request.user, invoice)

    if request.method == 'POST':
        if not can_edit:
            raise PermissionDenied()
        old_snapshot = {f: getattr(invoice, f) for f in _KEY_FIELDS}
        form = ChinaInvoiceForm(request.POST, request.FILES, instance=invoice)
        form.fields['invoice_file'].required = False
        if form.is_valid():
            updated = form.save(commit=False)
            if not request.FILES.get('invoice_file'):
                updated.invoice_file = invoice.invoice_file
            _reset_confirmations_if_key_changed(old_snapshot, updated)
            updated.save()
            _handle_packing_list_uploads(request, updated)
            messages.success(request, f'{updated.management_no} を更新しました。')
            return redirect('expenses:china_invoice_detail', pk=updated.pk)
    else:
        form = ChinaInvoiceForm(instance=invoice) if can_edit else None
        if form is not None:
            form.fields['invoice_file'].required = False

    return render(request, 'expenses/china_invoice_detail.html', {
        'invoice': invoice, 'form': form, 'can_edit': can_edit, 'current': 'china_invoice_list',
    })


@login_required
@require_POST
def china_invoice_packing_list_add(request, pk):
    invoice = get_object_or_404(T_ChinaInvoice, pk=pk)
    if not _can_edit(request.user, invoice):
        raise PermissionDenied()
    if request.method == 'POST':
        _handle_packing_list_uploads(request, invoice)
    return redirect('expenses:china_invoice_detail', pk=invoice.pk)


@login_required
@require_POST
def china_invoice_packing_list_delete(request, pk):
    packing_list = get_object_or_404(T_ChinaInvoicePackingList, pk=pk)
    if not _can_edit(request.user, packing_list.invoice):
        raise PermissionDenied()
    if request.method == 'POST':
        invoice_pk = packing_list.invoice_id
        packing_list.file.delete(save=False)
        packing_list.delete()
        return redirect('expenses:china_invoice_detail', pk=invoice_pk)
    return redirect('expenses:china_invoice_detail', pk=packing_list.invoice_id)
