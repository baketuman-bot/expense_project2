from django.urls import path
from . import views

app_name = "expenses"

urlpatterns = [
    path("", views.home, name="home"),
    # 新規申請ランチャー
    path("new/select/", views.expense_type_launcher, name="expense_type_launcher"),
    # 既定は DocType=1（支出伺い）を渡す（互換維持）
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
    path("approvals/<int:pk>/edit/", views.keiri_approval_edit, name="keiri_approval_edit"),
    # CSV エクスポート
    path("csv/", views.expense_csv, name="expense_csv"),
    path("approvals/csv/", views.approval_csv, name="approval_csv"),
    # API: 承認者候補（others 用）
    path("api/approver_candidates/", views.approver_candidates, name="approver_candidates"),
    # API: モバイル QR アップロード
    path("api/generate_mobile_qr/", views.generate_mobile_upload_qr, name="generate_mobile_qr"),
    path("api/check_mobile_uploads/", views.check_mobile_uploads, name="check_mobile_uploads"),
    # API: 固定資産番号オートフィル
    path("api/asset_lookup/", views.api_asset_lookup, name="api_asset_lookup"),
    # 固定資産
    path("assets/", views.asset_home, name="asset_home"),
    path("assets/list/", views.asset_list, name="asset_list"),
    path("assets/new/<int:document_type_id>/", views.expense_create, name="asset_create_by_type"),
    # 固定資産台帳（T_ASSETS）
    path("assets/register/new/", views.assets_register_create, name="assets_register_create"),
    path("assets/register/queue/", views.assets_sync_queue_list, name="assets_sync_queue_list"),
    path("assets/register/sync/", views.assets_sync_info, name="assets_sync_info"),
    path("assets/register/csv/", views.assets_register_csv, name="assets_register_csv"),
    path("assets/register/<str:asset_no>/edit/", views.assets_register_edit, name="assets_register_edit"),
    path("assets/register/", views.assets_register_list, name="assets_register_list"),
    # 少額資産台帳（T_AssetsLowValue）
    path("assets/low_value/csv/", views.assets_low_value_csv, name="assets_low_value_csv"),
    path("assets/low_value/", views.assets_low_value_list, name="assets_low_value_list"),
    # 改善要望
    path("feedback/", views.feedback_list, name="feedback_list"),
    path("feedback/new/", views.feedback_create, name="feedback_create"),
    path("feedback/<int:pk>/", views.feedback_detail, name="feedback_detail"),
    path("feedback/<int:pk>/edit/", views.feedback_edit, name="feedback_edit"),
    path("feedback/<int:pk>/delete/", views.feedback_delete, name="feedback_delete"),
    # 管理者画面 (設定)
    path("settings/data_view/", views.settings_data_view_home, name="settings_data_view_home"),
    path("settings/data_view/<str:view_name>/", views.settings_data_view_browse, name="settings_data_view_browse"),
    path("settings/data_view/<str:view_name>/csv/", views.settings_data_view_csv, name="settings_data_view_csv"),
    path("settings/", views.settings_home, name="settings_home"),
    path("settings/mail/", views.settings_mail, name="settings_mail"),
    path("settings/export/", views.settings_export, name="settings_export"),
    path("settings/approval_admin/", views.settings_approval_admin, name="settings_approval_admin"),
    path("settings/approval_admin/<int:pk>/", views.settings_approval_detail, name="settings_approval_detail"),
    path("settings/approval_admin/<int:pk>/action/", views.settings_force_action, name="settings_force_action"),
    # 精算処理
    path("settings/settlement/", views.settlement_menu, name="settlement_menu"),
    path("settings/settlement/list/", views.settlement_list, name="settlement_list"),
    path("settings/settlement/<int:pk>/toggle/", views.settlement_toggle, name="settlement_toggle"),
    path("settings/settlement/classify/", views.settlement_classify, name="settlement_classify"),
    path("settings/settlement/cash/hq/", views.settlement_cash_hq, name="settlement_cash_hq"),
    path("settings/settlement/cash/osaka/", views.settlement_cash_osaka, name="settlement_cash_osaka"),
    path("settings/settlement/cash/print/", views.settlement_cash_print, name="settlement_cash_print"),
    path("settings/settlement/transfer/", views.settlement_transfer, name="settlement_transfer"),
    path("settings/settlement/corp_card/", views.settlement_corp_card, name="settlement_corp_card"),
    path("settings/settlement/payroll/", views.settlement_payroll, name="settlement_payroll"),
    path("settings/settlement/auto_debit/", views.settlement_auto_debit, name="settlement_auto_debit"),
    # 仕訳処理
    path("settings/settlement/journal/",                views.settlement_journal,  name="settlement_journal"),
    path("settings/settlement/journal/entry/",          views.journal_entry,       name="journal_entry"),
    path("settings/settlement/journal/csv/",            views.journal_csv,         name="journal_csv"),
    path("settings/settlement/journal/<int:pk>/",       views.journal_detail_api,  name="journal_detail_api"),
    path("settings/settlement/journal/<int:pk>/save/",  views.journal_save,        name="journal_save"),
    path("settings/settlement/journal/<int:pk>/split/",  views.journal_split,        name="journal_split"),
    path("settings/settlement/journal/<int:pk>/delete/", views.journal_split_delete, name="journal_split_delete"),
    # 債務管理（口座振込 LON_INPRO 対象。仕訳処理と同じUIを共有）
    path("settings/settlement/debt/",       views.settlement_debt, name="settlement_debt"),
    path("settings/settlement/debt/entry/", views.debt_entry,      name="debt_entry"),
    path("settings/settlement/debt/csv/",   views.debt_csv,        name="debt_csv"),
    # マスタ設定
    path("settings/master/m_user/<int:pk>/toggle_active/", views.user_toggle_active, name="user_toggle_active"),
    path("settings/master/", views.settings_master_home, name="settings_master_home"),
    path("settings/master/<str:master_key>/", views.settings_master_list, name="settings_master_list"),
    path("settings/master/<str:master_key>/csv/", views.settings_master_csv, name="settings_master_csv"),
    path("settings/master/<str:master_key>/create/", views.settings_master_create, name="settings_master_create"),
    path("settings/master/<str:master_key>/<str:pk>/edit/", views.settings_master_edit, name="settings_master_edit"),
    path("settings/master/<str:master_key>/<str:pk>/delete/", views.settings_master_delete, name="settings_master_delete"),
]
