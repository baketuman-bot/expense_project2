from .models import M_DocumentGroup, T_DocumentApprover, T_Document


def sidebar_context(request):
    if not request.user.is_authenticated:
        return {}

    groups = (
        M_DocumentGroup.objects
        .filter(category='expense')
        .prefetch_related('document_types')
        .order_by('menu_order')
    )

    sidebar_groups = []
    for grp in groups:
        dt_list = list(grp.document_types.order_by('menu_order'))
        if dt_list:
            sidebar_groups.append((grp, dt_list))

    # 承認待ち件数（自分が承認者として登録されていて INPRO 状態の申請数）
    pending_approval_count = 0
    try:
        approver_doc_ids = T_DocumentApprover.objects.filter(
            man_number=request.user
        ).values_list('document_id', flat=True)
        pending_approval_count = T_Document.objects.filter(
            document_id__in=approver_doc_ids,
            status_cd__status_cd='INPRO',
        ).count()
    except Exception:
        pass

    return {
        'sidebar_expense_groups': sidebar_groups,
        'pending_approval_count': pending_approval_count,
    }
