from django.db import migrations

TABLE_COMMENTS = {
    'm_group': '所属部署マスタ',
    'm_bumon': '部門マスタ',
    'm_post': '役職マスタ',
    'm_status': 'ステータスマスタ',
    'm_user': 'ユーザーマスタ（AbstractUser拡張）',
    'm_user_role': 'ユーザーロール（1ユーザーに複数ロール可）',
    'm_account': '勘定科目マスタ',
    'm_account_sub': '補助科目マスタ',
    'm_item': '汎用項目マスタ（data_kbnで種別管理）',
    'm_mail_manage': 'メール送信管理マスタ',
    'm_workflow_templates': 'ワークフローテンプレートマスタ',
    'm_document_group': '文書グループマスタ（メニューグループ・カテゴリ管理）',
    'm_document_types': '文書種別マスタ',
    'm_document_field': '文書フィールドマスタ（動的フィールド定義）',
    'm_account_document': '文書種別勘定科目マスタ（DocType毎の表示勘定科目）',
    'm_workflow_steps': 'ワークフローステップマスタ',
    't_workflow_instances': 'ワークフローインスタンス（実行時）',
    't_workflow_actions': 'ワークフローアクション（承認・却下・差戻し履歴）',
    't_documents': '文書（申請ヘッダ）',
    't_documentcontents': '文書明細',
    't_document_edit_history': '経理修正履歴（経理担当による明細修正ログ）',
    't_document_attachments': '文書添付ファイル',
    'm_belong_to': '所属部署マッピング（ユーザーと部署の紐付け）',
    't_document_approvers': '文書承認者（承認予定者 事前計算）',
    't_feedback': '改善要望',
    't_settle': '精算ログ（明細ごとの精算処理履歴）',
    'T_ASSETS': '固定資産テーブル（Accessシステム連携 v_assetsビュー相当）',
    'M_ExchangeRate': '換算為替レートマスタ',
}

# (テーブル名, カラム名) -> コメント  ※カラム名はMySQLの実カラム名
COLUMN_COMMENTS = {
    # m_group
    ('m_group', 'group_cd'): '部署コード（PK）',
    ('m_group', 'group_name'): '部署名',
    ('m_group', 'upper_group_cd'): '上位部署コード（ツリー構造用）',
    # m_bumon
    ('m_bumon', 'bumon_cd'): '部門コード（PK）',
    ('m_bumon', 'bumon_name'): '部門名',
    ('m_bumon', 'cs_kbn'): 'CS区分',
    ('m_bumon', 'consumption_tax_kbn'): '消費税区分',
    # m_post
    ('m_post', 'post_cd'): '役職コード（PK）',
    ('m_post', 'post_name'): '役職名',
    ('m_post', 'post_order'): '職位順（値が小さいほど上位）',
    # m_status
    ('m_status', 'status_cd'): 'ステータスコード（PK） 例: DRA/SUB/INPRO/FNS/REJ',
    ('m_status', 'status_name'): 'ステータス名',
    ('m_status', 'action_name'): 'アクション名',
    ('m_status', 'order_by'): '表示順',
    ('m_status', 'status_kbn'): 'ステータス区分',
    # m_user
    ('m_user', 'id'): 'ユーザーID（PK Django標準）',
    ('m_user', 'man_number'): '社員番号（ログイン用ユニークキー）',
    ('m_user', 'user_name'): '氏名',
    ('m_user', 'bumon_cd_id'): '部門コード（FK: m_bumon）',
    ('m_user', 'post_cd_id'): '役職コード（FK: m_post）',
    ('m_user', 'email'): 'メールアドレス',
    ('m_user', 'is_active'): '有効フラグ',
    ('m_user', 'is_staff'): 'Django Adminアクセス用フラグ',
    ('m_user', 'is_superuser'): 'スーパーユーザーフラグ（Django Admin専用。アプリ内権限にはM_UserRoleを使用）',
    ('m_user', 'date_joined'): '登録日時',
    ('m_user', 'last_login'): '最終ログイン日時',
    ('m_user', 'username'): 'ユーザー名（Django標準）',
    ('m_user', 'password'): 'ハッシュ済みパスワード',
    # m_user_role
    ('m_user_role', 'id'): 'ID（PK）',
    ('m_user_role', 'man_number'): '社員番号（FK: m_user）',
    ('m_user_role', 'role'): 'ロール名 例: approver/accountant/final_approver/admin/keiri/assets',
    # m_account
    ('m_account', 'account_cd'): '勘定科目コード（PK）',
    ('m_account', 'account_name'): '勘定科目名',
    # m_account_sub
    ('m_account_sub', 'id'): 'ID（PK）',
    ('m_account_sub', 'account_cd'): '勘定科目コード（FK相当: m_account）',
    ('m_account_sub', 'sub_account_cd'): '補助科目コード',
    ('m_account_sub', 'sub_account_name'): '補助科目名',
    ('m_account_sub', 'pr_kbn'): '表示デフォルト区分（0:通常 1:デフォルト選択）',
    # m_item
    ('m_item', 'id'): 'ID（PK）',
    ('m_item', 'data_kbn'): 'データ区分 例: CUR/PAY/TRA/MST',
    ('m_item', 'key'): 'キー（data_kbn内でユニーク）',
    ('m_item', 'content'): '内容',
    ('m_item', 'content2'): '内容2',
    ('m_item', 'content3'): '内容3',
    ('m_item', 'order_by'): '表示順',
    # m_mail_manage
    ('m_mail_manage', 'mail_category'): 'メールカテゴリコード（PK）',
    ('m_mail_manage', 'mail_label'): 'カテゴリ名',
    ('m_mail_manage', 'mail_desc'): '説明',
    ('m_mail_manage', 'enabled'): 'メール送信有効フラグ',
    # m_workflow_templates
    ('m_workflow_templates', 'workflow_template_id'): 'ワークフローテンプレートID（PK）',
    ('m_workflow_templates', 'workflow_template_name'): 'ワークフローテンプレート名',
    ('m_workflow_templates', 'description'): '説明',
    # m_document_group
    ('m_document_group', 'menu_group'): 'グループコード（PK） 例: PAY/TRV/REC/AST/LON',
    ('m_document_group', 'menu_group_name'): 'グループ名（サイドバー表示）',
    ('m_document_group', 'category'): 'カテゴリ expense:費用精算 / assets:固定資産',
    ('m_document_group', 'menu_order'): 'サイドバー表示順',
    # m_document_types
    ('m_document_types', 'document_type_id'): '文書種別ID（PK）',
    ('m_document_types', 'document_type_name'): '文書種別名',
    ('m_document_types', 'description'): '説明',
    ('m_document_types', 'workflow_template_id'): 'ワークフローテンプレートID（FK: m_workflow_templates）',
    ('m_document_types', 'bumon_scope'): '負担部門スコープ 0:自グループ絞り込み / 1:全部門表示',
    ('m_document_types', 'menu_group'): '文書グループコード（FK: m_document_group）',
    ('m_document_types', 'menu_order'): 'メニュー表示順（サイドバー内での順序）',
    # m_document_field
    ('m_document_field', 'id'): 'ID（PK）',
    ('m_document_field', 'document_type_id'): '文書種別ID（FK: m_document_types）',
    ('m_document_field', 'field_name'): 'フィールド名（Djangoフォームフィールド名）',
    ('m_document_field', 'field_type'): 'フィールド型 例: text/number/date/select/label',
    ('m_document_field', 'field_name_view'): '表示名（ラベル）',
    ('m_document_field', 'field_order'): '表示順',
    ('m_document_field', 'col_width'): 'Bootstrap col-md-N カラム幅（1〜12）',
    ('m_document_field', 'row_break'): 'このフィールドの前で改行フラグ',
    ('m_document_field', 'required'): '必須入力フラグ',
    ('m_document_field', 'placeholder'): 'プレースホルダーテキスト',
    ('m_document_field', 'field_help_text'): '補助テキスト（フォーム下部に表示）',
    ('m_document_field', 'calc_formula'): '計算式（label型用） 例: {field1}+{field2}|単位',
    ('m_document_field', 'section_header'): 'セクション見出し（設定するとこのフィールドの前に区切り見出しを表示）',
    # m_account_document
    ('m_account_document', 'id'): 'ID（PK）',
    ('m_account_document', 'document_type_id'): '文書種別ID（FK: m_document_types）',
    ('m_account_document', 'account_cd'): '勘定科目コード（FK: m_account）',
    # m_workflow_steps
    ('m_workflow_steps', 'step_id'): 'ステップID（PK）',
    ('m_workflow_steps', 'workflow_template_id'): 'ワークフローテンプレートID（FK: m_workflow_templates）',
    ('m_workflow_steps', 'step_order'): 'ステップ順序',
    ('m_workflow_steps', 'step_type'): 'ステップ種別 approval:承認 / reception:受付 / confirmation:確認',
    ('m_workflow_steps', 'condition_expr'): '条件式（スキップ条件等）',
    ('m_workflow_steps', 'approver_post_cd'): '承認者役職コード（FK: m_post）',
    ('m_workflow_steps', 'allowed_post_cd'): '許可役職コード（FK: m_post）',
    ('m_workflow_steps', 'allowed_bumon_scope'): '部門許可範囲 same/parent/keiri/assets/any',
    ('m_workflow_steps', 'group_id'): 'グループID（スコープ絞り込み用）',
    # t_workflow_instances
    ('t_workflow_instances', 'instance_id'): 'インスタンスID（PK）',
    ('t_workflow_instances', 'document_id'): '文書ID（FK: t_documents）',
    ('t_workflow_instances', 'workflow_template_id'): 'ワークフローテンプレートID（FK: m_workflow_templates）',
    ('t_workflow_instances', 'status'): 'ステータス（FK: m_status）',
    ('t_workflow_instances', 'started_at'): '開始日時',
    ('t_workflow_instances', 'completed_at'): '完了日時',
    ('t_workflow_instances', 'step_id'): '現在ステップID（FK: m_workflow_steps）',
    ('t_workflow_instances', 'step_order'): '現在ステップ順（表示上の承認済み数 = step_order - 1）',
    # t_workflow_actions
    ('t_workflow_actions', 'action_id'): 'アクションID（PK）',
    ('t_workflow_actions', 'instance_id'): 'インスタンスID（FK: t_workflow_instances）',
    ('t_workflow_actions', 'step_id'): 'ステップID（FK: m_workflow_steps）',
    ('t_workflow_actions', 'approver_man_number'): '承認者社員番号（FK: m_user）',
    ('t_workflow_actions', 'action'): '操作ステータス（FK: m_status）',
    ('t_workflow_actions', 'comment'): 'コメント（連続ステップ自動承認時は「（連続ステップ自動承認）」）',
    ('t_workflow_actions', 'actioned_at'): '処理日時',
    # t_documents
    ('t_documents', 'document_id'): '文書ID（PK）',
    ('t_documents', 'document_type_id'): '文書種別ID（FK: m_document_types）',
    ('t_documents', 'title'): 'タイトル',
    ('t_documents', 'ringi_no'): '稟議No',
    ('t_documents', 'man_number'): '申請者社員番号（FK: m_user）',
    ('t_documents', 'bumon_cd'): '部門コード（FK: m_bumon）',
    ('t_documents', 'status_cd_id'): 'ステータスコード（FK: m_status）',
    ('t_documents', 'tsuka_cd'): '通貨コード 3桁 例: JPY/USD（m_item.data_kbn=CUR参照）',
    ('t_documents', 'memo'): 'メモ・備考',
    ('t_documents', 'pay_kbn'): '精算方法（m_item.data_kbn=PAY参照） 01:給与振込 02:現金 等',
    ('t_documents', 'created_at'): '作成日時',
    ('t_documents', 'updated_at'): '更新日時',
    ('t_documents', 'is_settled'): '精算完了フラグ（FNS後に経理がチェック）',
    ('t_documents', 'settled_at'): '精算完了日時',
    # t_documentcontents
    ('t_documentcontents', 'document_detail_id'): '明細ID（PK）',
    ('t_documentcontents', 'document_id'): '文書ID（FK: t_documents）',
    ('t_documentcontents', 'date'): '日付',
    ('t_documentcontents', 'account_id'): '勘定科目（FK: m_account）',
    ('t_documentcontents', 'tekikaku_cd'): '登録番号（適格請求書番号）',
    ('t_documentcontents', 'shiharaisaki'): '支払先',
    ('t_documentcontents', 'purpose'): '目的',
    ('t_documentcontents', 'amount'): '金額',
    ('t_documentcontents', 'content'): '内容JSON（TRVグループ: 経路・宿泊・日当情報を格納）',
    ('t_documentcontents', 'corpo_card'): 'コーポレートカード支払いフラグ',
    ('t_documentcontents', 'corpo_card_no'): 'カード番号下4桁',
    ('t_documentcontents', 'settle_kbn'): '精算区分',
    ('t_documentcontents', 'consumption_tax'): '消費税額',
    ('t_documentcontents', 'consumption_kbn'): '内外税区分',
    ('t_documentcontents', 'hojo_cd'): '補助科目コード（m_account_sub参照）',
    ('t_documentcontents', 'journal_tax_kbn'): '仕訳税区分',
    ('t_documentcontents', 'journal_tax_rate'): '仕訳税率',
    ('t_documentcontents', 'journal_fx_rate'): '換算レート（外貨明細用）',
    ('t_documentcontents', 'journal_done'): '仕訳入力済フラグ',
    # t_document_edit_history
    ('t_document_edit_history', 'edit_id'): '修正ID（PK）',
    ('t_document_edit_history', 'document_id'): '文書ID（FK: t_documents）',
    ('t_document_edit_history', 'document_detail_id'): '明細ID（FK: t_documentcontents）',
    ('t_document_edit_history', 'man_number'): '修正者社員番号（FK: m_user）',
    ('t_document_edit_history', 'field_name'): 'フィールド名（Pythonモデル属性名）',
    ('t_document_edit_history', 'field_label'): 'フィールドラベル（日本語表示名）',
    ('t_document_edit_history', 'old_value'): '変更前の値',
    ('t_document_edit_history', 'new_value'): '変更後の値',
    ('t_document_edit_history', 'edited_at'): '修正日時',
    # t_document_attachments
    ('t_document_attachments', 'attachment_id'): '添付ID（PK）',
    ('t_document_attachments', 'document_detail_id'): '明細ID（FK: t_documentcontents）',
    ('t_document_attachments', 'file'): '添付ファイルパス（GCS or ローカル /media/）',
    ('t_document_attachments', 'thumbnail'): 'サムネイル画像パス（PDF/画像から自動生成）',
    ('t_document_attachments', 'uploaded_at'): '登録日時',
    # m_belong_to  ※FKカラム名はDjangoデフォルト（man_number_id / group_cd_id）
    ('m_belong_to', 'belong_id'): '所属ID（PK）',
    ('m_belong_to', 'man_number_id'): '社員番号（FK: m_user）',
    ('m_belong_to', 'group_cd_id'): '部署コード（FK: m_group）',
    ('m_belong_to', 'created_at'): '作成日時',
    ('m_belong_to', 'updated_at'): '更新日時',
    # t_document_approvers
    ('t_document_approvers', 'id'): 'ID（PK）',
    ('t_document_approvers', 'document_id'): '文書ID（FK: t_documents）',
    ('t_document_approvers', 'step_id'): 'ステップID（FK: m_workflow_steps）',
    ('t_document_approvers', 'man_number'): '承認者社員番号（FK: m_user）',
    ('t_document_approvers', 'step_order'): 'ステップ順',
    ('t_document_approvers', 'status'): '承認ステータス pending/APPROVED/REJECTED',
    ('t_document_approvers', 'approved_at'): '承認日時',
    ('t_document_approvers', 'remarks'): '備考',
    ('t_document_approvers', 'created_at'): '作成日時',
    # t_feedback
    ('t_feedback', 'feedback_id'): '要望ID（PK）',
    ('t_feedback', 'man_number'): '申請者社員番号（FK: m_user）',
    ('t_feedback', 'request_text'): '要望事項',
    ('t_feedback', 'response_text'): '回答（is_superuserのみ編集可）',
    ('t_feedback', 'status_cd'): '状況 00:受付中 01:検討中 02:対応済 03:対応不可',
    ('t_feedback', 'created_at'): '登録日',
    ('t_feedback', 'updated_at'): '更新日',
    # t_settle
    ('t_settle', 'settle_id'): '精算ログID（PK）',
    ('t_settle', 'document_id'): '文書ID（FK: t_documents）',
    ('t_settle', 'document_detail_id'): '明細ID（FK: t_documentcontents）',
    ('t_settle', 'man_number'): '処理者社員番号（FK: m_user）',
    ('t_settle', 'status_cd'): '精算ステータス',
    ('t_settle', 'settle_ymd'): '精算日',
    ('t_settle', 'create_ymd'): '登録日',
    ('t_settle', 'update_ymd'): '更新日',
    # T_ASSETS
    ('T_ASSETS', 'asset_no'): '資産NO（PK 13桁）',
    ('T_ASSETS', 'account_cd'): '科目コード',
    ('T_ASSETS', 'account_name'): '科目名',
    ('T_ASSETS', 'bumon_cd'): '部門コード',
    ('T_ASSETS', 'bumon_name'): '部門名',
    ('T_ASSETS', 'accounting_bumon_cd'): '会計用部門コード',
    ('T_ASSETS', 'asset_name1'): '資産名１',
    ('T_ASSETS', 'asset_name2'): '資産名２',
    ('T_ASSETS', 'structure_cd'): '構造細目コード',
    ('T_ASSETS', 'structure_name'): '構造名',
    ('T_ASSETS', 'detail_name'): '細目名',
    ('T_ASSETS', 'alloc_kbn'): '部門配賦区分',
    ('T_ASSETS', 'alloc_rate_cd'): '配賦率コード',
    ('T_ASSETS', 'quantity'): '個数',
    ('T_ASSETS', 'unit'): '単位',
    ('T_ASSETS', 'useful_life'): '耐用年数',
    ('T_ASSETS', 'depreciation_start_date'): '償却開始日',
    ('T_ASSETS', 'acquisition_date'): '取得日',
    ('T_ASSETS', 'transfer_date'): '異動増日付',
    ('T_ASSETS', 'installation_date'): '設置日',
    ('T_ASSETS', 'disposal_date'): '除却日',
    ('T_ASSETS', 'registration_date'): '固定登録日',
    ('T_ASSETS', 'disposal_registration_date'): '除却登録日',
    ('T_ASSETS', 'transfer_registration_date'): '異動登録日',
    ('T_ASSETS', 'special_registration_date'): '特割登録日',
    ('T_ASSETS', 'depreciation_stop_start_date'): '償却停止開始日',
    ('T_ASSETS', 'depreciation_stop_end_date'): '償却停止終了日',
    ('T_ASSETS', 'straight_line_switch_date'): '定額切換日',
    ('T_ASSETS', 'acquisition_amount'): '取得価額',
    ('T_ASSETS', 'beginning_amount'): '期首価額',
    ('T_ASSETS', 'beginning_depreciation_diff'): '期首償却過不足額',
    ('T_ASSETS', 'residual_amount'): '残存価額',
    ('T_ASSETS', 'current_optional_depreciation'): '当期任意償却額',
    ('T_ASSETS', 'compression_reserve'): '圧縮引当金',
    ('T_ASSETS', 'beginning_adjustment'): '期首価額調整額',
    ('T_ASSETS', 'depreciation_limit'): '償却可能限度額',
    ('T_ASSETS', 'disposal_amount'): '処分価額',
    ('T_ASSETS', 'special_depreciation_amount'): '特別償却額',
    ('T_ASSETS', 'extra_depreciation_amount'): '割増償却額',
    ('T_ASSETS', 'prev_year_book_amount'): '前年申告帳簿価額',
    ('T_ASSETS', 'prev_year_assessed_amount'): '前年申告評価額',
    ('T_ASSETS', 'switch_book_amount'): '切換時帳簿価額',
    ('T_ASSETS', 'post_switch_annual_depreciation'): '切換後年償却額',
    ('T_ASSETS', 'current_optional_kbn'): '当期任意償却区分',
    ('T_ASSETS', 'special_rate_input_kbn'): '特例率入力区分',
    ('T_ASSETS', 'collateral_kbn'): '担保資産区分',
    ('T_ASSETS', 'special_depreciation_kbn'): '特別償却計算区分',
    ('T_ASSETS', 'extra_depreciation_kbn'): '割増償却計算区分',
    ('T_ASSETS', 'tax_target_kbn'): '納税対象区分',
    ('T_ASSETS', 'increase_reason'): '増加事由',
    ('T_ASSETS', 'disposal_kbn'): '除却区分',
    ('T_ASSETS', 'decrease_kbn'): '減少区分',
    ('T_ASSETS', 'location_cd'): '設置場所コード',
    ('T_ASSETS', 'location_name'): '設置場所名',
    ('T_ASSETS', 'city_cd'): '市区町村コード',
    ('T_ASSETS', 'city_name'): '市区町村名',
    ('T_ASSETS', 'special_rate_numerator'): '特例率分子',
    ('T_ASSETS', 'special_rate_denominator'): '特例率分母',
    ('T_ASSETS', 'source_asset_no'): '異動元資産NO',
    ('T_ASSETS', 'supplier_cd'): '購入先コード',
    ('T_ASSETS', 'partial_expansion_asset_cd'): '一部増設元資産コード',
    ('T_ASSETS', 'ringi_no'): '稟議NO',
    ('T_ASSETS', 'manager'): '管理者',
    ('T_ASSETS', 'memo1'): 'メモ欄',
    ('T_ASSETS', 'memo2'): 'メモ欄２',
    ('T_ASSETS', 'model_name'): 'モデル',
    ('T_ASSETS', 'serial_no'): 'シリアルNO',
    ('T_ASSETS', 'physical_inventory_result'): '実地調査結果',
    # M_ExchangeRate
    ('M_ExchangeRate', 'id'): 'ID（PK）',
    ('M_ExchangeRate', 'keijo_ym'): '計上年月（YYYYMM形式）',
    ('M_ExchangeRate', 'tsuka_cd'): '通貨コード 例: USD/EUR',
    ('M_ExchangeRate', 'exchange_rate'): '換算レート（1外貨あたりの円換算額）',
}


def add_comments(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return

    conn = schema_editor.connection
    db_name = conn.settings_dict['NAME']

    with conn.cursor() as cursor:
        # テーブルコメントを設定
        for table, comment in TABLE_COMMENTS.items():
            try:
                cursor.execute(f"ALTER TABLE `{table}` COMMENT = %s", [comment])
            except Exception:
                pass

        # information_schema からカラム定義を一括取得
        tables = list({t for t, _ in COLUMN_COMMENTS})
        fmt = ','.join(['%s'] * len(tables))
        cursor.execute(f"""
            SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE,
                   COLUMN_DEFAULT, EXTRA, CHARACTER_SET_NAME, COLLATION_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({fmt})
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """, [db_name] + tables)

        col_info = {}
        for row in cursor.fetchall():
            col_info[(row[0], row[1])] = row[2:]

        # カラムコメントを MODIFY COLUMN で設定
        for (table, col), comment in COLUMN_COMMENTS.items():
            info = col_info.get((table, col))
            if info is None:
                continue
            col_type, is_nullable, default, extra, charset, collation = info

            parts = [col_type]
            if charset:
                parts.append(f'CHARACTER SET {charset}')
            if collation:
                parts.append(f'COLLATE {collation}')
            parts.append('NOT NULL' if is_nullable == 'NO' else 'NULL')

            extra_lower = (extra or '').lower()
            if 'auto_increment' in extra_lower:
                parts.append('AUTO_INCREMENT')
            elif 'default_generated' in extra_lower:
                if default:
                    parts.append(f'DEFAULT {default}')
                if 'on update' in extra_lower:
                    idx = extra_lower.index('on update')
                    parts.append(extra[idx:].upper())
            elif 'on update' in extra_lower:
                if default is not None:
                    parts.append(f'DEFAULT {default}')
                idx = extra_lower.index('on update')
                parts.append(extra[idx:].upper())
            elif default is not None:
                str_def = str(default)
                if str_def.lower().startswith('current_timestamp') or str_def.upper() == 'NULL':
                    parts.append(f'DEFAULT {str_def}')
                else:
                    parts.append(f"DEFAULT '{str_def}'")
            elif is_nullable == 'YES':
                parts.append('DEFAULT NULL')

            col_def = ' '.join(parts)
            sql = f'ALTER TABLE `{table}` MODIFY COLUMN `{col}` {col_def} COMMENT %s'
            try:
                cursor.execute(sql, [comment])
            except Exception:
                pass


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0083_add_pr_kbn_to_m_account_sub'),
    ]

    operations = [
        migrations.RunPython(add_comments, migrations.RunPython.noop),
    ]
