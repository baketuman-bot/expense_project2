"""中国輸出Invoice管理: 報告ウィザード（ステップ1 提出 / ステップ2 確認・報告確定）。

ステップ1でドロップされたInvoiceファイルは china_invoice_batch が一時保管し、
ステップ2の「報告」でまとめて T_ChinaInvoice を作成する。
DBへの書き込みは報告確定時の1トランザクションのみ。
"""
import datetime
import logging
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from .china_invoice_batch import create_batch, discard_batch, get_batch, remove_item
from .china_invoice_files import validate_china_invoice_file
from .china_invoice_pdf import extract_invoice_fields
from .forms import ChinaInvoiceRowFormSet
from .models import M_Item
from .views_china_invoice import _is_month_closed, _require_role

logger = logging.getLogger(__name__)

CURRENT_MENU = 'china_invoice_report'


@login_required
def china_invoice_report_upload(request):
    """ステップ1: Invoiceファイルを複数ドロップして提出する。"""
    _require_role(request.user, 'china_reporter')
    today = datetime.date.today()
    month_closed = _is_month_closed(today)

    if request.method == 'POST':
        errors = []
        if month_closed:
            errors.append('今月は月締め済みのため報告できません。')
        files = request.FILES.getlist('invoice_files')
        if not files:
            errors.append('Invoiceファイルを選択してください。')
        for uploaded in files:
            try:
                validate_china_invoice_file(uploaded)
            except ValidationError as e:
                errors.extend(f'{uploaded.name}: {m}' for m in e.messages)

        if errors:
            logger.warning('Invoice提出の検証エラー: %s', errors)
            for msg in errors:
                messages.error(request, msg)
            return render(request, 'expenses/china_invoice_report_upload.html', {
                'month_closed': month_closed, 'current': CURRENT_MENU,
            })

        extracted = []
        for uploaded in files:
            if os.path.splitext(uploaded.name)[1].lower() == '.pdf':
                uploaded.seek(0)
                extracted.append(extract_invoice_fields(uploaded.read()))
                uploaded.seek(0)
            else:
                extracted.append({'invoice_no': None, 'invoice_total': None})

        create_batch(request, files, extracted)
        return redirect('expenses:china_invoice_report_review')

    # 前回の未確定バッチを掃除してから提出画面を出す
    discard_batch(request)
    return render(request, 'expenses/china_invoice_report_upload.html', {
        'month_closed': month_closed, 'current': CURRENT_MENU,
    })


def _review_context(batch, formset):
    """ステップ2のテンプレートcontext。rowsは(form, item)のペアで、位置で対応させる。"""
    return {
        'formset': formset,
        'rows': list(zip(formset.forms, batch['items'])),
        'cargo_categories': M_Item.objects.filter(
            data_kbn='CHN_CARGO').order_by('order_by', 'key'),
        'adjustment_rates': M_Item.objects.filter(
            data_kbn='CHN_ADJRT').order_by('order_by', 'key'),
        'row_count': len(batch['items']),
        'unread_count': sum(
            1 for i in batch['items'] if not i['invoice_no'] or not i['invoice_total']),
        'current': CURRENT_MENU,
    }


@login_required
def china_invoice_report_review(request):
    """ステップ2: 読取結果の確認・修正・行の除外・キャンセル。報告確定はTask 6で実装する。"""
    _require_role(request.user, 'china_reporter')
    batch = get_batch(request)
    if not batch or not batch['items']:
        messages.error(request, '報告するInvoiceがありません。ファイルを選択してください。')
        return redirect('expenses:china_invoice_report_upload')

    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'cancel':
            discard_batch(request)
            messages.info(request, '報告を取り消しました。')
            return redirect('expenses:china_invoice_report_upload')
        if action.startswith('remove_'):
            try:
                index = int(action[len('remove_'):])
            except ValueError:
                return redirect('expenses:china_invoice_report_review')
            remaining = remove_item(request, index)
            if remaining == 0:
                discard_batch(request)
                messages.info(request, 'すべてのInvoiceを除外したため、報告を取り消しました。')
                return redirect('expenses:china_invoice_report_upload')
            return redirect('expenses:china_invoice_report_review')
        return redirect('expenses:china_invoice_report_review')

    formset = ChinaInvoiceRowFormSet(initial=[
        {
            'index': item['index'],
            'invoice_no': item['invoice_no'] or '',
            'invoice_total': item['invoice_total'] or '',
        }
        for item in batch['items']
    ])
    return render(request, 'expenses/china_invoice_report_review.html',
                  _review_context(batch, formset))
