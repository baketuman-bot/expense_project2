"""
各テーブルのリレーションを解決した DB VIEW の SQL 定義。
migration 0048 後方互換用の V_DOCUMENT_FULL_* は残す。
migration 0049 以降は ALL_VIEWS を使用。
"""

# ── 後方互換（0048 マイグレーション用）──────────────────────────────────────
V_DOCUMENT_FULL_CREATE = "SELECT 1"   # 0048 は既に適用済みのため空文字は避け無害なSQL
V_DOCUMENT_FULL_DROP   = "DROP VIEW IF EXISTS v_document_full"

# ── 個別 VIEW SQL ─────────────────────────────────────────────────────────────

_V_DOCUMENT_TYPES = """
CREATE OR REPLACE VIEW v_document_types AS
SELECT
  t.document_type_id,
  t.document_type_name,
  t.description,
  t.workflow_template_id,
  w.workflow_template_name,
  t.bumon_scope,
  t.menu_group       AS menu_group_cd,
  g.menu_group_name,
  g.category,
  g.menu_order       AS group_menu_order,
  t.menu_order
FROM m_document_types t
LEFT JOIN m_workflow_templates w
  ON w.workflow_template_id = t.workflow_template_id
LEFT JOIN m_document_group g
  ON g.menu_group = t.menu_group
"""

_V_ACCOUNT_DOCUMENT = """
CREATE OR REPLACE VIEW v_account_document AS
SELECT
  mad.id,
  mad.document_type_id,
  dt.document_type_name,
  mad.account_cd,
  a.account_name
FROM m_account_document mad
LEFT JOIN m_document_types dt ON dt.document_type_id = mad.document_type_id
LEFT JOIN m_account a         ON a.account_cd        = mad.account_cd
"""

_V_BELONG_TO = """
CREATE OR REPLACE VIEW v_belong_to AS
SELECT
  bt.belong_id,
  bt.man_number_id  AS man_number,
  u.user_name,
  bt.group_cd_id    AS group_cd,
  g.group_name,
  g.upper_group_cd,
  bt.created_at,
  bt.updated_at
FROM m_belong_to bt
LEFT JOIN m_user  u ON u.man_number = bt.man_number_id
LEFT JOIN m_group g ON g.group_cd   = bt.group_cd_id
"""

_V_DOCUMENT_FIELD = """
CREATE OR REPLACE VIEW v_document_field AS
SELECT
  mdf.id,
  mdf.document_type_id,
  dt.document_type_name,
  mdf.field_name,
  mdf.field_type,
  mdf.field_name_view,
  mdf.field_order,
  mdf.col_width,
  mdf.row_break,
  mdf.required,
  mdf.placeholder,
  mdf.field_help_text,
  mdf.calc_formula,
  mdf.section_header
FROM m_document_field mdf
LEFT JOIN m_document_types dt ON dt.document_type_id = mdf.document_type_id
"""

_V_USERS = """
CREATE OR REPLACE VIEW v_users AS
SELECT
  u.id,
  u.man_number,
  u.user_name,
  u.email,
  u.is_superuser,
  u.is_active,
  u.bumon_cd_id   AS bumon_cd,
  b.bumon_name,
  u.post_cd_id    AS post_cd,
  p.post_name,
  p.post_order
FROM m_user u
LEFT JOIN m_bumon b ON b.bumon_cd = u.bumon_cd_id
LEFT JOIN m_post  p ON p.post_cd  = u.post_cd_id
"""

_V_WORKFLOW_STEPS = """
CREATE OR REPLACE VIEW v_workflow_steps AS
SELECT
  ws.step_id,
  ws.workflow_template_id,
  wt.workflow_template_name,
  ws.step_order,
  ws.step_type,
  ws.condition_expr,
  ws.approver_post_cd,
  ap.post_name  AS approver_post_name,
  ap.post_order AS approver_post_order,
  ws.allowed_post_cd,
  lp.post_name  AS allowed_post_name,
  ws.allowed_bumon_scope,
  ws.group_id
FROM m_workflow_steps ws
LEFT JOIN m_workflow_templates wt ON wt.workflow_template_id = ws.workflow_template_id
LEFT JOIN m_post ap ON ap.post_cd = ws.approver_post_cd
LEFT JOIN m_post lp ON lp.post_cd = ws.allowed_post_cd
"""

_V_DOCUMENT_APPROVERS = """
CREATE OR REPLACE VIEW v_document_approvers AS
SELECT
  da.id,
  da.document_id,
  d.title         AS document_title,
  da.step_id,
  ws.step_order   AS ws_step_order,
  ws.step_type,
  ws.allowed_bumon_scope,
  da.man_number   AS approver_man_number,
  u.user_name     AS approver_name,
  da.step_order,
  da.status,
  da.approved_at,
  da.remarks,
  da.created_at
FROM t_document_approvers da
LEFT JOIN t_documents      d  ON d.document_id = da.document_id
LEFT JOIN m_workflow_steps ws ON ws.step_id    = da.step_id
LEFT JOIN m_user           u  ON u.man_number  = da.man_number
"""

_V_DOCUMENTCONTENTS = """
CREATE OR REPLACE VIEW v_documentcontents AS
SELECT
  dc.document_detail_id,
  dc.document_id,
  d.title             AS document_title,
  d.document_type_id,
  dt.document_type_name,
  g.menu_group_name,
  g.category,
  d.man_number        AS applicant_man_number,
  u.user_name         AS applicant_name,
  d.bumon_cd,
  b.bumon_name,
  d.tsuka_cd,
  d.memo,
  d.ringi_no,
  d.created_at        AS document_created_at,
  d.is_settled,
  d.settled_at,
  dc.date,
  dc.account_id       AS account_cd,
  a.account_name,
  dc.tekikaku_cd,
  dc.shiharaisaki,
  dc.purpose,
  dc.amount,
  dc.corpo_card,
  dc.corpo_card_no,
  d.pay_kbn,
  dc.settle_kbn,
  d.status_cd_id
FROM t_documentcontents dc
LEFT JOIN t_documents      d  ON d.document_id       = dc.document_id
LEFT JOIN m_document_types dt ON dt.document_type_id = d.document_type_id
LEFT JOIN m_document_group g  ON g.menu_group        = dt.menu_group
LEFT JOIN m_account        a  ON a.account_cd        = dc.account_id
LEFT JOIN m_user           u  ON u.man_number        = d.man_number
LEFT JOIN m_bumon          b  ON b.bumon_cd          = d.bumon_cd
"""

_V_DOCUMENTS = """
CREATE OR REPLACE VIEW v_documents AS
SELECT
  d.document_id,
  d.title,
  d.ringi_no,
  d.document_type_id,
  dt.document_type_name,
  g.menu_group_name,
  g.category,
  d.man_number          AS applicant_man_number,
  u.user_name           AS applicant_name,
  d.bumon_cd            AS charge_bumon_cd,
  b.bumon_name          AS charge_bumon_name,
  d.status_cd_id        AS status_cd,
  s.status_name,
  d.tsuka_cd,
  d.pay_kbn,
  d.memo,
  d.created_at,
  d.updated_at
FROM t_documents d
LEFT JOIN m_document_types dt ON dt.document_type_id = d.document_type_id
LEFT JOIN m_document_group g  ON g.menu_group        = dt.menu_group
LEFT JOIN m_user           u  ON u.man_number        = d.man_number
LEFT JOIN m_bumon          b  ON b.bumon_cd          = d.bumon_cd
LEFT JOIN m_status         s  ON s.status_cd         = d.status_cd_id
"""

_V_FEEDBACK = """
CREATE OR REPLACE VIEW v_feedback AS
SELECT
  tf.feedback_id,
  tf.man_number   AS applicant_man_number,
  u.user_name     AS applicant_name,
  u.email         AS applicant_email,
  tf.request_text,
  tf.response_text,
  tf.status_cd,
  tf.created_at,
  tf.updated_at
FROM t_feedback tf
LEFT JOIN m_user u ON u.man_number = tf.man_number
"""

_V_WORKFLOW_ACTIONS = """
CREATE OR REPLACE VIEW v_workflow_actions AS
SELECT
  wa.action_id,
  wa.instance_id,
  wi.document_id,
  wa.step_id,
  ws.step_order,
  ws.step_type,
  wa.approver_man_number,
  u.user_name          AS approver_name,
  wa.action            AS action_status_cd,
  ms.status_name       AS action_status_name,
  wa.comment,
  wa.actioned_at
FROM t_workflow_actions wa
LEFT JOIN t_workflow_instances wi ON wi.instance_id  = wa.instance_id
LEFT JOIN m_workflow_steps     ws ON ws.step_id      = wa.step_id
LEFT JOIN m_user               u  ON u.man_number    = wa.approver_man_number
LEFT JOIN m_status             ms ON ms.status_cd    = wa.action
"""

_V_WORKFLOW_INSTANCES = """
CREATE OR REPLACE VIEW v_workflow_instances AS
SELECT
  wi.instance_id,
  wi.document_id,
  d.title              AS document_title,
  d.document_type_id,
  dt.document_type_name,
  wi.workflow_template_id,
  wt.workflow_template_name,
  wi.status            AS wf_status_cd,
  ms.status_name       AS wf_status_name,
  wi.step_id,
  ws.step_order        AS ws_step_order,
  ws.step_type,
  ws.allowed_bumon_scope,
  wi.step_order        AS current_step_order,
  wi.started_at,
  wi.completed_at
FROM t_workflow_instances wi
LEFT JOIN t_documents          d  ON d.document_id          = wi.document_id
LEFT JOIN m_document_types     dt ON dt.document_type_id    = d.document_type_id
LEFT JOIN m_workflow_templates wt ON wt.workflow_template_id= wi.workflow_template_id
LEFT JOIN m_status             ms ON ms.status_cd           = wi.status
LEFT JOIN m_workflow_steps     ws ON ws.step_id             = wi.step_id
"""

_V_SETTLE = """
CREATE OR REPLACE VIEW v_settle AS
SELECT
  s.settle_id,
  s.document_id,
  d.title             AS document_title,
  d.document_type_id,
  dt.document_type_name,
  d.man_number        AS applicant_man_number,
  au.user_name        AS applicant_name,
  d.bumon_cd,
  b.bumon_name,
  s.document_detail_id,
  dc.date             AS detail_date,
  dc.amount           AS detail_amount,
  dc.shiharaisaki,
  dc.purpose,
  s.status_cd,
  s.settle_ymd,
  s.man_number        AS processor_man_number,
  pu.user_name        AS processor_name,
  s.create_ymd,
  s.update_ymd
FROM t_settle s
LEFT JOIN t_documents      d   ON d.document_id       = s.document_id
LEFT JOIN m_document_types dt  ON dt.document_type_id = d.document_type_id
LEFT JOIN m_user           au  ON au.man_number        = d.man_number
LEFT JOIN m_bumon          b   ON b.bumon_cd           = d.bumon_cd
LEFT JOIN t_documentcontents dc ON dc.document_detail_id = s.document_detail_id
LEFT JOIN m_user           pu  ON pu.man_number        = s.man_number
"""

# ── 公開辞書（migration 0049 / 管理コマンドで使用）──────────────────────────
ALL_VIEWS = {
    'v_document_types':      _V_DOCUMENT_TYPES,
    'v_account_document':    _V_ACCOUNT_DOCUMENT,
    'v_belong_to':           _V_BELONG_TO,
    'v_document_field':      _V_DOCUMENT_FIELD,
    'v_users':               _V_USERS,
    'v_workflow_steps':      _V_WORKFLOW_STEPS,
    'v_document_approvers':  _V_DOCUMENT_APPROVERS,
    'v_documentcontents':    _V_DOCUMENTCONTENTS,
    'v_documents':           _V_DOCUMENTS,
    'v_feedback':            _V_FEEDBACK,
    'v_workflow_actions':    _V_WORKFLOW_ACTIONS,
    'v_workflow_instances':  _V_WORKFLOW_INSTANCES,
    'v_settle':              _V_SETTLE,
}
