from django.db.models import Subquery, OuterRef, Exists
from .models import M_DocumentGroup, T_DocumentApprover, T_Document, T_WorkflowInstance


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

    # 承認待ち件数: 自分が現在のワークフローステップの担当者（pending）として
    # 登録されており、かつ INPRO 状態の申請数
    # role='approver' / is_superuser は INPRO 全件を対象（特権）
    pending_approval_count = 0
    try:
        if request.user.role == 'approver' or request.user.is_superuser:
            pending_approval_count = T_Document.objects.filter(
                status_cd__status_cd='INPRO'
            ).count()
        else:
            # current_step_subq は is_my_turn (T_DocumentApprover) の内側で評価されるため
            # OuterRef('document_id') = T_DocumentApprover.document_id を参照する
            current_step_subq = T_WorkflowInstance.objects.filter(
                document_id=OuterRef('document_id')  # T_DocumentApprover.document_id
            ).order_by('-started_at').values('step_id')[:1]

            is_my_turn = T_DocumentApprover.objects.filter(
                document_id=OuterRef('pk'),           # T_Document.pk
                man_number=request.user,
                status='pending',
                step_id=Subquery(current_step_subq),  # 現在のステップと一致するか
            )

            pending_approval_count = T_Document.objects.filter(
                status_cd__status_cd='INPRO'
            ).filter(Exists(is_my_turn)).count()
    except Exception:
        pass

    return {
        'sidebar_expense_groups': sidebar_groups,
        'pending_approval_count': pending_approval_count,
    }
