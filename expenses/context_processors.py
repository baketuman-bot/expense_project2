from .models import M_DocumentGroup


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

    return {'sidebar_expense_groups': sidebar_groups}
