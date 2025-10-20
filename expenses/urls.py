from django.urls import path
from . import views

app_name = "expenses"

urlpatterns = [
    path("", views.home, name="home"),
    # 既定は DocType=1（支出伺い）を渡す
    path("new/", views.expense_create, {"document_type_id": 1}, name="expense_create"),
    # 将来的に DocType を切り替えたい場合の可変ルート
    path("new/<int:document_type_id>/", views.expense_create, name="expense_create_by_type"),
    path("list/", views.expense_list, name="expense_list"),
    path("<int:pk>/", views.expense_detail, name="expense_detail"),
    path("<int:pk>/edit/", views.expense_edit, name="expense_edit"),
    path("approvals/", views.approval_list, name="approval_list"),
    path("approvals/<int:pk>/", views.approval_detail, name="approval_detail"),
    # API: 承認者候補（others 用）
    path("api/approver_candidates/", views.approver_candidates, name="approver_candidates"),
]
