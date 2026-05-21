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
    path("<int:pk>/delete/", views.expense_delete, name="expense_delete"),
    path("<int:pk>/copy/", views.expense_copy, name="expense_copy"),
    path("approvals/", views.approval_list, name="approval_list"),
    path("approvals/<int:pk>/", views.approval_detail, name="approval_detail"),
    # CSV エクスポート
    path("csv/", views.expense_csv, name="expense_csv"),
    path("approvals/csv/", views.approval_csv, name="approval_csv"),
    # API: 承認者候補（others 用）
    path("api/approver_candidates/", views.approver_candidates, name="approver_candidates"),
    # API: モバイル QR アップロード
    path("api/generate_mobile_qr/", views.generate_mobile_upload_qr, name="generate_mobile_qr"),
    path("api/check_mobile_uploads/", views.check_mobile_uploads, name="check_mobile_uploads"),
    # 固定資産
    path("assets/", views.asset_home, name="asset_home"),
    path("assets/list/", views.asset_list, name="asset_list"),
    path("assets/new/<int:document_type_id>/", views.expense_create, name="asset_create_by_type"),
    # 改善要望
    path("feedback/", views.feedback_list, name="feedback_list"),
    path("feedback/new/", views.feedback_create, name="feedback_create"),
    path("feedback/<int:pk>/", views.feedback_detail, name="feedback_detail"),
    path("feedback/<int:pk>/edit/", views.feedback_edit, name="feedback_edit"),
    path("feedback/<int:pk>/delete/", views.feedback_delete, name="feedback_delete"),
    # 管理者画面 (設定)
    path("settings/data_view/", views.settings_data_view_home, name="settings_data_view_home"),
    path("settings/data_view/<str:view_name>/", views.settings_data_view_browse, name="settings_data_view_browse"),
    path("settings/", views.settings_home, name="settings_home"),
    path("settings/export/", views.settings_export, name="settings_export"),
    path("settings/approval_admin/", views.settings_approval_admin, name="settings_approval_admin"),
    path("settings/approval_admin/<int:pk>/", views.settings_approval_detail, name="settings_approval_detail"),
    path("settings/approval_admin/<int:pk>/action/", views.settings_force_action, name="settings_force_action"),
    # マスタ設定
    path("settings/master/", views.settings_master_home, name="settings_master_home"),
    path("settings/master/<str:master_key>/", views.settings_master_list, name="settings_master_list"),
    path("settings/master/<str:master_key>/create/", views.settings_master_create, name="settings_master_create"),
    path("settings/master/<str:master_key>/<str:pk>/edit/", views.settings_master_edit, name="settings_master_edit"),
    path("settings/master/<str:master_key>/<str:pk>/delete/", views.settings_master_delete, name="settings_master_delete"),
]
