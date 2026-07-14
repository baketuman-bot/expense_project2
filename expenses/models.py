from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from decimal import Decimal

# 所属部署マスタ
class M_Group(models.Model):
    group_cd = models.CharField("部署コード", max_length=20, primary_key=True)
    group_name = models.CharField("部署名", max_length=50)
    upper_group_cd = models.CharField("上位部署コード", max_length=20, null=True, blank=True)

    def __str__(self):
        return f"{self.group_name} ({self.group_cd})"

    class Meta:
        db_table = 'm_group'
        verbose_name = '所属部署マスタ'
        verbose_name_plural = '所属部署マスタ'

# 部門マスタ
class M_Bumon(models.Model):
    bumon_cd = models.CharField("部門コード", max_length=15, primary_key=True, default='DEFAULT')
    bumon_name = models.CharField("部門名", max_length=100)
    cs_kbn = models.SmallIntegerField("CS区分", null=True, blank=True)
    consumption_tax_kbn = models.SmallIntegerField("消費税区分", null=True, blank=True)

    def __str__(self):
        return self.bumon_name

    class Meta:
        db_table = 'm_bumon'


# 役職マスタ
class M_Post(models.Model):
    post_cd = models.CharField("役職コード", max_length=15, primary_key=True, default='DEFAULT')
    post_name = models.CharField("役職名", max_length=100)
    post_order = models.IntegerField("職位順", default=0, help_text="小さいほど上位の扱い")

    def __str__(self):
        return self.post_name

    class Meta:
        db_table = 'm_post'


# ステータスマスタ
class M_Status(models.Model):
    status_cd = models.CharField("ステータスコード", max_length=20, primary_key=True, default='DEFAULT')
    status_name = models.CharField("ステータス名", max_length=50)
    action_name = models.CharField("アクション名", max_length=50, null=True, blank=True)
    order_by = models.IntegerField("表示順", default=100)
    status_kbn = models.CharField("ステータス区分", max_length=3, null=True, blank=True)

    def __str__(self):
        return self.status_name

    class Meta:
        db_table = 'm_status'
        ordering = ['order_by', 'status_cd']


# ユーザーマスタ（AbstractUser拡張）
class M_User(AbstractUser):
    # Django 標準の username, password, email などに加えて独自フィールドを追加
    man_number = models.CharField("社員番号", max_length=20, unique=True)
    user_name = models.CharField("氏名", max_length=30)
    bumon_cd = models.ForeignKey(M_Bumon, verbose_name="部門", on_delete=models.PROTECT, null=True, blank=True)
    post_cd = models.ForeignKey(M_Post, verbose_name="役職", on_delete=models.PROTECT, null=True, blank=True)

    groups = None
    user_permissions = None

    def has_role(self, role_name):
        """M_UserRole に role_name が登録されているか判定する。"""
        return self.roles.filter(role=role_name).exists()

    def __str__(self):
        return self.user_name

    class Meta:
        db_table = 'm_user'


class M_UserRole(models.Model):
    man_number = models.ForeignKey(
        M_User,
        to_field='man_number',
        db_column='man_number',
        on_delete=models.CASCADE,
        related_name='roles',
        verbose_name='社員番号',
    )
    role = models.CharField("ロール", max_length=50)

    class Meta:
        db_table = 'm_user_role'
        unique_together = ('man_number', 'role')
        verbose_name = 'ユーザーロール'
        verbose_name_plural = 'ユーザーロール'


# 勘定科目マスタ
class M_Account(models.Model):
    account_cd = models.CharField("勘定科目コード", max_length=20, primary_key=True, default='DEFAULT')
    account_name = models.CharField("勘定科目名", max_length=100)

    def __str__(self):
        return self.account_name

    class Meta:
        db_table = 'm_account'


# 補助科目マスタ
class M_AccountSub(models.Model):
    account_cd = models.CharField("勘定科目コード", max_length=20)
    sub_account_cd = models.CharField("補助科目コード", max_length=5)
    sub_account_name = models.CharField("補助科目名", max_length=50)
    pr_kbn = models.SmallIntegerField("表示デフォルト区分", default=0)

    def __str__(self):
        return f"{self.account_cd} / {self.sub_account_cd} {self.sub_account_name}"

    class Meta:
        db_table = 'm_account_sub'
        unique_together = [('account_cd', 'sub_account_cd')]
        ordering = ['account_cd', 'sub_account_cd']
        verbose_name = '補助科目マスタ'
        verbose_name_plural = '補助科目マスタ'


# 汎用項目マスタ
class M_Item(models.Model):
    data_kbn = models.CharField("データ区分", max_length=10, blank=True)
    key = models.CharField("キー", max_length=20, blank=True)
    content = models.CharField("内容", max_length=50, blank=True)
    content2 = models.CharField("内容2", max_length=50)
    content3 = models.CharField("内容3", max_length=30, blank=True)
    order_by = models.IntegerField("表示順", null=True, blank=True)

    class Meta:
        db_table = 'm_item'
        verbose_name = '汎用項目マスタ'
        verbose_name_plural = '汎用項目マスタ'
        constraints = [
            models.UniqueConstraint(fields=["data_kbn", "key"], name="uq_m_item_data_kbn_key"),
        ]

    def __str__(self):
        return f"{self.key} - {self.content}"


# メール送信管理マスタ
class M_MailManage(models.Model):
    mail_category = models.CharField("メールカテゴリ", max_length=20, primary_key=True)
    mail_label    = models.CharField("カテゴリ名",    max_length=100)
    mail_desc     = models.CharField("説明",          max_length=255, blank=True)
    enabled       = models.BooleanField("送信する", default=True)

    class Meta:
        db_table = 'm_mail_manage'
        verbose_name = 'メール送信管理'
        verbose_name_plural = 'メール送信管理'

    def __str__(self):
        return f"{self.mail_label}({'ON' if self.enabled else 'OFF'})"


# ワークフローテンプレートマスタ
class M_WorkflowTemplate(models.Model):
    workflow_template_id = models.AutoField("ワークフローテンプレートID", primary_key=True, db_column='workflow_template_id')
    workflow_template_name = models.CharField("ワークフローテンプレート名", max_length=100)
    description = models.TextField("説明", null=True, blank=True)

    def __str__(self):
        return self.workflow_template_name

    class Meta:
        db_table = 'm_workflow_templates'
        verbose_name = 'ワークフローテンプレートマスタ'
        verbose_name_plural = 'ワークフローテンプレートマスタ'


# 文書グループマスタ（menu_group / category のマスタ化）
class M_DocumentGroup(models.Model):
    CATEGORY_CHOICES = [
        ('expense', '費用精算'),
        ('assets',  '固定資産'),
    ]

    menu_group      = models.CharField("グループコード", max_length=50, primary_key=True)
    menu_group_name = models.CharField("グループ名",     max_length=50)
    category        = models.CharField(
        "カテゴリ", max_length=20, choices=CATEGORY_CHOICES, default='expense'
    )
    menu_order      = models.SmallIntegerField("表示順", default=0)

    def __str__(self):
        return self.menu_group_name

    class Meta:
        db_table = 'm_document_group'
        verbose_name = '文書グループマスタ'
        verbose_name_plural = '文書グループマスタ'
        ordering = ['menu_order']


# 文書種別マスタ
class M_DocumentType(models.Model):
    BUMON_SCOPE_ALL = 1
    BUMON_SCOPE_GROUP = 0
    BUMON_SCOPE_CHOICES = [
        (BUMON_SCOPE_GROUP, '自グループ絞り込み'),
        (BUMON_SCOPE_ALL,   '全部門'),
    ]

    document_type_id = models.AutoField("文書種別ID", primary_key=True, db_column='document_type_id')
    document_type_name = models.CharField("文書種別名", max_length=100)
    description = models.TextField("説明", null=True, blank=True)
    workflow_template_id = models.ForeignKey(
        'M_WorkflowTemplate',
        verbose_name="ワークフローテンプレート",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='workflow_template_id'
    )
    bumon_scope = models.SmallIntegerField(
        "負担部門スコープ",
        choices=BUMON_SCOPE_CHOICES,
        default=BUMON_SCOPE_GROUP,
        help_text="0: 自グループ絞り込み / 1: 全部門表示",
    )
    menu_group = models.ForeignKey(
        'M_DocumentGroup',
        verbose_name="文書グループ",
        to_field='menu_group',
        db_column='menu_group',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_constraint=False,
        related_name='document_types',
    )
    menu_order = models.SmallIntegerField(
        "メニュー表示順",
        default=0,
        help_text="サイドバーでの表示順（小さい値が先）",
    )

    def __str__(self):
        return self.document_type_name

    class Meta:
        db_table = 'm_document_types'
        verbose_name = '文書種別マスタ'
        verbose_name_plural = '文書種別マスタ'


# 文書種別ごとのカスタムフィールド定義マスタ
class M_DocumentField(models.Model):
    document_type = models.ForeignKey(
        M_DocumentType,
        verbose_name="文書種別",
        on_delete=models.PROTECT,
        db_column='document_type_id',
        related_name='document_fields'
    )
    field_name = models.CharField("フィールド名", max_length=30)
    field_type = models.CharField("フィールド型", max_length=30)
    field_name_view = models.CharField("表示名", max_length=30, null=True, blank=True, default='')
    # レイアウト制御
    field_order    = models.IntegerField("表示順", default=0)
    col_width      = models.IntegerField("幅(col-md-N 1〜12)", default=4)
    row_break      = models.BooleanField("この前で改行", default=False)
    required       = models.BooleanField("必須", default=False)
    placeholder    = models.CharField("プレースホルダー", max_length=100, blank=True, default='')
    field_help_text = models.CharField("補助テキスト", max_length=200, blank=True, default='')
    # label型専用: 計算式 例) {client_num}+{staff_num}|人  {amount_total}/{total_num}|円/人
    calc_formula   = models.CharField("計算式(label型用)", max_length=200, blank=True, default='')
    # セクション見出し: 設定するとこのフィールドの直前に区切り見出しを表示
    section_header = models.CharField("セクション見出し", max_length=100, blank=True, default='')

    def __str__(self):
        try:
            return f"{self.document_type_id} - {self.field_name} ({self.field_type})"
        except Exception:
            return f"{self.field_name} ({self.field_type})"

    class Meta:
        db_table = 'm_document_field'
        verbose_name = '文書フィールドマスタ'
        verbose_name_plural = '文書フィールドマスタ'
        unique_together = [['document_type', 'field_name']]
        ordering = ['document_type', 'field_order', 'field_name']

# 文書種別ごとの表示勘定科目マスタ
class M_AccountDocument(models.Model):
    document_type = models.ForeignKey(
        M_DocumentType,
        verbose_name="文書種別",
        on_delete=models.PROTECT,
        db_column='document_type_id',
        related_name='account_documents',
        db_constraint=False,
    )
    account_cd = models.ForeignKey(
        M_Account,
        verbose_name="勘定科目",
        on_delete=models.PROTECT,
        db_column='account_cd',
        to_field='account_cd',
        related_name='account_documents',
        db_constraint=False,
    )

    def __str__(self):
        return f"{self.document_type} - {self.account_cd}"

    class Meta:
        db_table = 'm_account_document'
        verbose_name = '文書種別勘定科目マスタ'
        verbose_name_plural = '文書種別勘定科目マスタ'
        unique_together = [['document_type', 'account_cd']]
        ordering = ['document_type', 'account_cd']

# ワークフローステップマスタ
class M_WorkflowStep(models.Model):
    STEP_TYPE_CHOICES = [
        ('approval', '承認'),
        ('reception', '受付'),
        ('confirmation', '確認'),
    ]

    BUMON_SCOPE_CHOICES = [
        ('same', '同一'),
        ('parent', '親'),
        ('keiri', '経理'),
        ('assets', '固定資産'),
        ('any', '全体'),
    ]

    workflow_template = models.ForeignKey(
        'M_WorkflowTemplate',
        verbose_name="ワークフローテンプレート",
        on_delete=models.PROTECT,
        db_column='workflow_template_id',
        related_name='steps'
    )
    step_id = models.AutoField("ステップID", primary_key=True)
    step_order = models.IntegerField("順序")
    step_type = models.CharField("ステップ種別", max_length=13, choices=STEP_TYPE_CHOICES, default='approval')
    condition_expr = models.CharField("条件式", max_length=255, null=True, blank=True)
    approver_post = models.ForeignKey(
        M_Post,
        to_field='post_cd',
        db_column='approver_post_cd',
        verbose_name="承認者役職",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='approver_workflow_steps'
    )
    allowed_post = models.ForeignKey(
        M_Post,
        to_field='post_cd',
        db_column='allowed_post_cd',
        verbose_name="許可役職",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='allowed_workflow_steps'
    )
    allowed_bumon_scope = models.CharField("部門許可範囲", max_length=7, choices=BUMON_SCOPE_CHOICES, default='any')
    group_id = models.IntegerField("グループID", null=True, blank=True)

    def __str__(self):
        return f"{self.workflow_template_id} - {self.step_order} ({self.step_type})"

    class Meta:
        db_table = 'm_workflow_steps'
        verbose_name = 'ワークフローステップマスタ'
        verbose_name_plural = 'ワークフローステップマスタ'
        ordering = ['workflow_template', 'step_order']


# ワークフローインスタンス
class T_WorkflowInstance(models.Model):
    instance_id = models.AutoField("インスタンスID", primary_key=True)
    # t_documents の文書ID
    document_id = models.ForeignKey(
        'T_Document',
        verbose_name="文書",
        on_delete=models.PROTECT,
        db_column='document_id',
        related_name='workflow_instances',
        db_constraint=False,
    )
    workflow_template = models.ForeignKey(
        'M_WorkflowTemplate',
        verbose_name="ワークフローテンプレート",
        on_delete=models.PROTECT,
        db_column='workflow_template_id',
        related_name='instances'
    )
    # ステータスは M_Status を参照（既存DBの 'status' カラムを流用）
    status = models.ForeignKey(
        'M_Status',
        verbose_name="ステータス",
        on_delete=models.PROTECT,
        db_column='status',
        db_constraint=False,
        null=True,
        blank=True,
    )
    started_at = models.DateTimeField("開始日時", default=timezone.now)
    completed_at = models.DateTimeField("完了日時", null=True, blank=True)
    # 現在のステップ（m_workflow_steps と同じカラム名をDBに持たせる）
    step = models.ForeignKey(
        'M_WorkflowStep',
        verbose_name="現在ステップ",
        on_delete=models.PROTECT,
        db_column='step_id',
        related_name='workflow_instances_current',
        null=True,
        blank=True,
        db_constraint=False,
    )
    step_order = models.IntegerField("現在ステップ順", db_column='step_order', null=True, blank=True)

    def __str__(self):
        return f"{self.instance_id} - {self.status}"

    class Meta:
        db_table = 't_workflow_instances'
        verbose_name = 'ワークフローインスタンス'
        verbose_name_plural = 'ワークフローインスタンス'


# ワークフローアクション（承認・却下・差戻し）
class T_WorkflowAction(models.Model):
    action_id = models.AutoField("アクションID", primary_key=True)
    instance = models.ForeignKey(
        T_WorkflowInstance,
        verbose_name="ワークフローインスタンス",
        on_delete=models.PROTECT,
        db_column='instance_id',
        related_name='actions'
    )
    step = models.ForeignKey(
        'M_WorkflowStep',
        verbose_name="対象ステップ",
        on_delete=models.PROTECT,
        db_column='step_id',
        related_name='actions'
    )
    approver_man_number = models.ForeignKey(
        M_User,
        to_field='man_number',
        db_column='approver_man_number',
        verbose_name="承認者社員番号",
        on_delete=models.PROTECT,
    )
    # 操作ステータスは M_Status を参照（既存DBの 'action' カラムを流用）
    action_status = models.ForeignKey(
        'M_Status',
        verbose_name="操作",
        on_delete=models.PROTECT,
        db_column='action',
        db_constraint=False,
        null=True,
        blank=True,
    )
    comment = models.TextField("コメント", null=True, blank=True)
    actioned_at = models.DateTimeField("処理日時", default=timezone.now)

    def __str__(self):
        try:
            label = self.action_status.status_cd if self.action_status else "-"
        except Exception:
            label = "-"
        return f"{self.instance_id} - {label}"

    class Meta:
        db_table = 't_workflow_actions'
        verbose_name = 'ワークフローアクション'
        verbose_name_plural = 'ワークフローアクション'
        ordering = ['-actioned_at']


# 文書（汎用ワークフロー対象）
class T_Document(models.Model):
    document_id = models.AutoField("文書ID", primary_key=True, db_column='document_id')
    document_type = models.ForeignKey(
        M_DocumentType,
        verbose_name="文書種別",
        on_delete=models.PROTECT,
        db_column='document_type_id',
        related_name='documents'
    )
    title = models.CharField("タイトル", max_length=255)
    ringi_no = models.CharField("稟議No", max_length=20, db_column='ringi_no', null=True, blank=True)
    man_number = models.ForeignKey(
        M_User,
        to_field='man_number',
        db_column='man_number',
        verbose_name="申請者",
        on_delete=models.PROTECT,
        related_name='documents'
    )
    bumon_cd = models.ForeignKey(
        M_Bumon,
        verbose_name="部門",
        on_delete=models.PROTECT,
        db_column='bumon_cd',
        null=True,
        blank=True,
        related_name='documents'
    )
    status_cd = models.ForeignKey(
        M_Status,
        verbose_name="ステータス",
        on_delete=models.PROTECT,
        db_column='status_cd_id',
    )
    # 通貨コード（3桁）。m_item(DATA_KBN='CUR') における KEY と一致する値を保持する。
    # Django の外部キー要件（参照先フィールドはユニーク必須）により、
    # DB レベルのFK制約は設けず、アプリ側で選択肢/バリデーションにより整合性を担保する。
    tsuka_cd = models.CharField("通貨コード", max_length=3, db_column='tsuka_cd', null=True, blank=True)
    memo = models.TextField("メモ", null=True, blank=True)
    # 精算方法（01:給与振込 / 02:現金 / 03:精算者以外へ支払 等）。m_item(DATA_KBN='PAY') と連動。
    pay_kbn = models.CharField("精算方法", max_length=2, db_column='pay_kbn', null=True, blank=True)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)
    is_settled = models.BooleanField("精算完了", default=False, db_column='is_settled')
    settled_at = models.DateTimeField(
        "精算開始日時", null=True, blank=True, db_column='settled_at',
        help_text='精算処理を開始した日（未精算データ分類画面で設定）。精算完了日ではない。',
    )

    def __str__(self):
        return f"{self.document_id} - {self.title}"

    # 互換プロパティ: 旧UI/テンプレートが参照する属性名を提供
    @property
    def applicant(self):
        return self.man_number

    @property
    def details(self):
        # 旧: expense.details → 新: document.contents
        return self.contents

    @property
    def total_amount(self):
        # 明細の金額合計（None は 0 として扱う）
        # prefetch_related('contents') 使用時はキャッシュを利用するため .all() で走査する
        total = Decimal('0')
        for c in self.contents.all():
            if c.amount:
                total += Decimal(c.amount)
        return total

    @property
    def expense_main_id(self):
        # 旧 UI 互換のための別名
        return self.document_id

    class Meta:
        db_table = 't_documents'
        verbose_name = '文書'
        verbose_name_plural = '文書'


import os
from django.conf import settings
import io
from django.core.files.base import ContentFile

# 画像/PDF 処理ライブラリは環境により未インストールのことがあるため遅延インポート
def _safe_import_pil():
    try:
        from PIL import Image  # type: ignore
        return Image
    except Exception:
        return None

def _safe_import_pdf2image():
    try:
        from pdf2image import convert_from_path  # type: ignore
        return convert_from_path
    except Exception:
        return None

def _safe_import_pymupdf():
    try:
        import fitz  # PyMuPDF
        return fitz
    except Exception:
        return None


# 互換用: 旧マイグレーション（0001_initial 等）が参照するアップロード関数
# 旧実装では T_ExpenseDetail 用に申請ID/明細IDベースのパスを返していたが、
# ここでは既存テーブルの適用や履歴読込を阻害しないよう、安全な固定フォーマットを返す。
def receipt_upload_path(instance, filename):  # noqa: F401
    base = os.path.basename(filename)
    ts = timezone.now().strftime('%Y%m%d%H%M%S')
    return f'receipts/legacy/{ts}_{base}'


def thumbnail_upload_path(instance, filename):  # noqa: F401
    name, _ = os.path.splitext(os.path.basename(filename))
    ts = timezone.now().strftime('%Y%m%d%H%M%S')
    return f'receipts/legacy/thumbnails/{ts}_{name}_thumb.jpg'



# 汎用ドキュメント用の領収書アップロード先
def document_receipt_upload_path(instance, filename):
    # PK未確定でも保存できるよう、明細IDは使わずタイムスタンプで一意化
    base = os.path.basename(filename)
    ts = timezone.now().strftime('%Y%m%d%H%M%S')
    return f'receipts/documents/{instance.document.document_id}/{ts}_{base}'


def document_thumbnail_upload_path(instance, filename):
    # サムネイル用のパス（明細ID非依存）
    ts = timezone.now().strftime('%Y%m%d%H%M%S')
    name, _ = os.path.splitext(os.path.basename(filename))
    return f'receipts/documents/{instance.document.document_id}/thumbnails/{ts}_{name}_thumb.jpg'

# 添付ファイル用のアップロード先（複数添付対応）
def attachment_upload_path(instance, filename):
    ts = timezone.now().strftime('%Y%m%d%H%M%S')
    base = os.path.basename(filename)
    return f'receipts/documents/{instance.detail.document.document_id}/attachments/{ts}_{base}'

def attachment_thumbnail_upload_path(instance, filename):
    ts = timezone.now().strftime('%Y%m%d%H%M%S')
    name, _ = os.path.splitext(os.path.basename(filename))
    return f'receipts/documents/{instance.detail.document.document_id}/attachments/thumbnails/{ts}_{name}_thumb.jpg'


class DocumentContentManager(models.Manager):
    """仕訳分割行（split_from が設定された行）を除外するデフォルトマネージャ。

    逆参照（doc.contents）にもこのフィルタが継承されるため、
    申請詳細・合計計算・CSV出力等の申請側コードには分割行が現れない。
    分割行を含めて扱う仕訳系ビューは all_objects を使うこと。
    """
    def get_queryset(self):
        return super().get_queryset().filter(split_from__isnull=True)


# ドキュメント明細
class T_DocumentContent(models.Model):
    document_detail_id = models.AutoField("明細ID", primary_key=True, db_column='document_detail_id')
    document = models.ForeignKey(
        'T_Document',
        verbose_name="文書",
        on_delete=models.CASCADE,
        db_column='document_id',
        related_name='contents'
    )
    date = models.DateField("日付", null=True, blank=True)
    account = models.ForeignKey(
        M_Account,
        verbose_name="勘定科目",
        on_delete=models.PROTECT,
        db_column='account_id',
        null=True,
        blank=True,
        related_name='document_contents'
    )
    tekikaku_cd = models.CharField("登録番号", max_length=15, null=True, blank=True)
    shiharaisaki = models.CharField("支払先", max_length=255, null=True, blank=True)
    purpose = models.CharField("目的", max_length=255, null=True, blank=True)
    amount = models.DecimalField("金額", max_digits=10, decimal_places=2, null=True, blank=True)
    content = models.JSONField("内容JSON", null=True, blank=True)
    corpo_card = models.IntegerField("コーポレートカード支払い", null=True, blank=True)
    corpo_card_no = models.CharField("カード番号", max_length=10, null=True, blank=True)
    settle_kbn = models.CharField("精算区分", max_length=10, null=True, blank=True, db_column='settle_kbn')
    consumption_tax = models.DecimalField("消費税額", max_digits=10, decimal_places=2, null=True, blank=True)
    consumption_kbn = models.SmallIntegerField("内外税区分", null=True, blank=True)
    # 仕訳作成フィールド
    hojo_cd        = models.CharField("補助科目コード", max_length=10,  null=True, blank=True)
    journal_tax_kbn  = models.CharField("仕訳税区分",   max_length=10,  null=True, blank=True)
    journal_tax_rate = models.CharField("仕訳税率",      max_length=10,  null=True, blank=True)
    journal_fx_rate  = models.CharField("換算レート",    max_length=20,  null=True, blank=True)
    journal_done     = models.BooleanField("仕訳入力済", default=False)
    journal_at       = models.DateField("仕訳処理日", null=True, blank=True)
    # 仕訳借方フィールド
    journal_amont           = models.DecimalField("借方税抜金額",    max_digits=10, decimal_places=2, null=True, blank=True)
    journal_tax             = models.DecimalField("借方税額",        max_digits=10, decimal_places=2, null=True, blank=True)
    journal_amont_fx        = models.DecimalField("借方税抜外貨",    max_digits=10, decimal_places=2, null=True, blank=True)
    journal_tax_fx          = models.DecimalField("借方税額外貨",    max_digits=10, decimal_places=2, null=True, blank=True)
    journal_discription_deb = models.CharField("借方適用",          max_length=50,  null=True, blank=True)
    # 仕訳貸方フィールド
    account_cd_cre          = models.CharField("貸方科目コード",     max_length=20,  null=True, blank=True)
    account_sub_cd_cre      = models.CharField("貸方補助科目コード", max_length=10,  null=True, blank=True)
    journal_amount_cre      = models.DecimalField("貸方税抜金額",    max_digits=10, decimal_places=2, null=True, blank=True)
    journal_amont_fx_cre    = models.DecimalField("貸方税抜外貨",    max_digits=10, decimal_places=2, null=True, blank=True)
    journal_tori_cd_cre     = models.CharField("貸方取引先コード",   max_length=10,  null=True, blank=True)
    journal_discription_cre = models.CharField("貸方摘要",          max_length=50,  null=True, blank=True)

    # 債務管理データ作成用フィールド
    supplier_cd = models.CharField("仕入先コード", max_length=10, null=True, blank=True)
    item_cd     = models.CharField("品目コード",   max_length=30, null=True, blank=True)
    qty         = models.IntegerField("数量", null=True, blank=True, db_column='Qty')

    # 仕訳分割: 元明細への自己参照（NULL=通常明細、非NULL=仕訳入力で作られた分割行）
    split_from = models.ForeignKey(
        'self',
        verbose_name="分割元明細",
        null=True, blank=True,
        on_delete=models.CASCADE,
        db_column='split_from_id',
        related_name='splits',
        db_comment='仕訳分割の元明細ID（NULL=通常明細）',
    )

    objects     = DocumentContentManager()  # 分割行を除外（申請側の既定）
    all_objects = models.Manager()          # 全件（仕訳系ビュー専用）

    # 旧フィールド（receipt/receipt_thumbnail）廃止に伴い、サムネイル生成や save の上書きは不要

    @property
    def voucher_date(self):
        """伝票日付: 精算開始日(document.settled_at)があればそれを優先、なければ明細日付にフォールバック"""
        settled_at = self.document.settled_at
        if settled_at is None:
            return self.date
        return settled_at.date() if hasattr(settled_at, 'date') else settled_at

    def __str__(self):
        return f"{self.document_detail_id} - {self.purpose or ''}"

    class Meta:
        db_table = 't_documentcontents'
        verbose_name = '文書明細'
        verbose_name_plural = '文書明細'


# 経理修正履歴
class T_DocumentEditHistory(models.Model):
    edit_id = models.AutoField("修正ID", primary_key=True)
    document = models.ForeignKey(
        T_Document, verbose_name="文書", on_delete=models.CASCADE,
        related_name='edit_histories', db_column='document_id'
    )
    detail = models.ForeignKey(
        T_DocumentContent, verbose_name="明細", on_delete=models.SET_NULL,
        null=True, blank=True, related_name='edit_histories', db_column='document_detail_id'
    )
    man_number = models.ForeignKey(
        'M_User', to_field='man_number', on_delete=models.CASCADE,
        db_column='man_number', verbose_name="修正者"
    )
    field_name = models.CharField("フィールド名", max_length=100)
    field_label = models.CharField("フィールドラベル", max_length=100, blank=True)
    old_value = models.TextField("変更前", blank=True, default='')
    new_value = models.TextField("変更後", blank=True, default='')
    edited_at = models.DateTimeField("修正日時", auto_now_add=True)

    class Meta:
        db_table = 't_document_edit_history'
        ordering = ['-edited_at']
        verbose_name = '経費修正履歴'
        verbose_name_plural = '経費修正履歴'

    def __str__(self):
        return f"#{self.document_id} {self.field_label or self.field_name}: {self.old_value} → {self.new_value}"


# 明細に紐づく複数添付
class T_DocumentAttachment(models.Model):
    attachment_id = models.AutoField("添付ID", primary_key=True, db_column='attachment_id')
    detail = models.ForeignKey(
        T_DocumentContent,
        verbose_name="明細",
        on_delete=models.PROTECT,
        db_column='document_detail_id',
        related_name='attachments'
    )
    file = models.FileField("添付ファイル", upload_to=attachment_upload_path)
    thumbnail = models.ImageField("サムネイル", upload_to=attachment_thumbnail_upload_path, null=True, blank=True)
    uploaded_at = models.DateTimeField("登録日時", auto_now_add=True)

    class Meta:
        db_table = 't_document_attachments'
        verbose_name = '文書添付'
        verbose_name_plural = '文書添付'

    def __str__(self):
        try:
            return f"{self.detail_id} - {os.path.basename(self.file.name)}"
        except Exception:
            return str(self.pk)

    def _generate_thumbnail(self):
        Image = _safe_import_pil()
        if not self.file:
            return
        _, ext = os.path.splitext(self.file.name)
        ext = (ext or '').lower()
        if ext == '.pdf':
            # PyMuPDF で PDF 1ページ目をサムネイル化（poppler 不要）
            # super().save() より前に呼ばれるためファイルはまだディスクにない
            # → stream= でメモリ上のバイト列から直接開く
            fitz = _safe_import_pymupdf()
            if fitz:
                try:
                    f = self.file
                    if hasattr(f, 'read'):
                        f.seek(0)
                        pdf_bytes = f.read()
                        f.seek(0)
                    else:
                        with open(os.path.join(settings.MEDIA_ROOT, f.name), 'rb') as fp:
                            pdf_bytes = fp.read()
                    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
                    if doc.page_count > 0:
                        page = doc[0]
                        mat = fitz.Matrix(1.5, 1.5)
                        pix = page.get_pixmap(matrix=mat)
                        pil_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        pil_img.thumbnail((400, 400))
                        thumb_io = io.BytesIO()
                        pil_img.save(thumb_io, format='JPEG', quality=85)
                        img_bytes = thumb_io.getvalue()
                        doc.close()
                        orig = os.path.basename(self.file.name)
                        name, _ = os.path.splitext(orig)
                        target_path = attachment_thumbnail_upload_path(self, f"{name}_thumb.jpg")
                        self.thumbnail.save(target_path, ContentFile(img_bytes), save=False)
                except Exception:
                    pass
        # 画像ファイルは元データを詳細画面で直接表示するためサムネイル不要

    def save(self, *args, **kwargs):
        if self.file and not self.thumbnail:
            try:
                self._generate_thumbnail()
            except Exception:
                pass
        super().save(*args, **kwargs)

# 組織関係ビュー
class V_Group(models.Model):
    group_cd = models.CharField("部署コード", max_length=20)
    relation_group_cd = models.CharField("関連部署コード", max_length=20)

    class Meta:
        managed = False  # マイグレーション対象外
        db_table = 'v_group'
        verbose_name = '組織関係ビュー'
        verbose_name_plural = '組織関係ビュー'

    def __str__(self):
        return f"{self.group_cd} - {self.relation_group_cd}"

# ユーザ情報ビュー（DBビュー v_user を参照／マイグレーション対象外）
class V_User(models.Model):
    man_number = models.CharField("社員番号", max_length=20, primary_key=True)
    user_name = models.CharField("氏名", max_length=30)
    group_cd = models.CharField("部署コード", max_length=20, null=True, blank=True)
    group_name = models.CharField("部署名", max_length=50, null=True, blank=True)
    bumon_cd = models.CharField("部門コード", max_length=15, null=True, blank=True)
    bumon_name = models.CharField("部門名", max_length=100, null=True, blank=True)
    post_cd = models.CharField("役職コード", max_length=15, null=True, blank=True)
    post_name = models.CharField("役職名", max_length=100, null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'v_user'
        verbose_name = 'ユーザビュー'
        verbose_name_plural = 'ユーザビュー'

    def __str__(self):
        return f"{self.user_name}({self.man_number})"

# 所属部署マッピング
class M_BelongTo(models.Model):
    belong_id = models.AutoField("所属ID", primary_key=True)
    man_number = models.ForeignKey(
        M_User, 
        verbose_name="社員", 
        to_field='man_number',  # man_numberフィールドを参照
        on_delete=models.CASCADE,
        related_name='belongs'
    )
    group_cd = models.ForeignKey(
        M_Group,
        verbose_name="所属部署",
        to_field='group_cd',
        on_delete=models.PROTECT
    )
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    def __str__(self):
        return f"{self.man_number.user_name} - {self.group_cd.group_name}"

    class Meta:
        db_table = 'm_belong_to'
        verbose_name = '所属部署マッピング'
        verbose_name_plural = '所属部署マッピング'
        unique_together = [['man_number', 'group_cd']]  # 同じ組み合わせの重複を防ぐ
        ordering = ['man_number', 'group_cd']

# 承認履歴
"""
旧: T_ApprovalLog は履歴の主たる用途を T_WorkflowAction に移行したため廃止しました。
DB 上にテーブルが残っていても ORM からは参照しません。
"""


# 文書ごとの承認者（承認予定者）
class T_DocumentApprover(models.Model):
    id = models.BigAutoField("ID", primary_key=True)
    # 既存カラム名を維持しつつ外部キー化（DB制約は付与しない）
    document_id = models.ForeignKey(
        'T_Document',
        verbose_name="文書",
        on_delete=models.PROTECT,
        db_column='document_id',
        related_name='document_approvers',
        db_constraint=False,
    )
    step_id = models.ForeignKey(
        M_WorkflowStep,
        verbose_name="ステップ",
        on_delete=models.PROTECT,
        db_column='step_id',
        related_name='document_approvers',
        db_constraint=False,
    )
    man_number = models.ForeignKey(
        M_User,
        to_field='man_number',
        db_column='man_number',
        verbose_name="承認者",
        on_delete=models.PROTECT,
        related_name='document_approvals',
        db_constraint=False,
    )
    step_order = models.IntegerField("ステップ順")
    status = models.CharField("ステータス", max_length=20, default='pending')
    approved_at = models.DateTimeField("承認日時", null=True, blank=True)
    remarks = models.TextField("備考", null=True, blank=True)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    def __str__(self):
        return f"doc={self.document_id_id}, step={self.step_id_id}, man={self.man_number_id}, status={self.status}"

    class Meta:
        db_table = 't_document_approvers'
        verbose_name = '文書承認者'
        verbose_name_plural = '文書承認者'


class T_Feedback(models.Model):
    STATUS_CHOICES = [
        ('00', '受付中'),
        ('01', '検討中'),
        ('02', '対応済'),
        ('03', '対応不可'),
    ]

    feedback_id  = models.AutoField("要望ID", primary_key=True)
    man_number   = models.ForeignKey(
        M_User,
        to_field='man_number',
        db_column='man_number',
        verbose_name="申請者",
        on_delete=models.PROTECT,
        related_name='feedbacks',
        null=True, blank=True,
        db_constraint=False,
    )
    request_text  = models.CharField("要望事項", max_length=100)
    response_text = models.CharField("回答", max_length=100, blank=True, default='')
    status_cd     = models.CharField("状況", max_length=2, choices=STATUS_CHOICES, default='00')
    created_at    = models.DateField("登録日", auto_now_add=True)
    updated_at    = models.DateField("更新日", auto_now=True)

    def __str__(self):
        return f"#{self.feedback_id} {self.request_text[:20]}"

    class Meta:
        db_table = 't_feedback'
        verbose_name = '改善要望'
        verbose_name_plural = '改善要望'
        ordering = ['-created_at', '-feedback_id']


class T_Settle(models.Model):
    """精算ログ: 明細ごとの精算処理履歴"""
    settle_id = models.AutoField("精算ログID", primary_key=True)
    document = models.ForeignKey(
        T_Document,
        verbose_name="文書",
        on_delete=models.CASCADE,
        db_column='document_id',
        related_name='settle_logs',
        db_constraint=False,
    )
    document_detail = models.ForeignKey(
        T_DocumentContent,
        verbose_name="明細",
        on_delete=models.CASCADE,
        db_column='document_detail_id',
        related_name='settle_logs',
        null=True, blank=True,
        db_constraint=False,
    )
    man_number = models.ForeignKey(
        M_User,
        to_field='man_number',
        db_column='man_number',
        verbose_name="処理者",
        on_delete=models.PROTECT,
        related_name='settle_logs',
        null=True, blank=True,
        db_constraint=False,
    )
    status_cd = models.CharField("精算ステータス", max_length=20, null=True, blank=True)
    settle_ymd = models.DateField("精算日", null=True, blank=True)
    create_ymd = models.DateField("登録日", auto_now_add=True)
    update_ymd = models.DateField("更新日", auto_now=True)

    def __str__(self):
        return f"settle#{self.settle_id} doc={self.document_id} {self.status_cd}"

    class Meta:
        db_table = 't_settle'
        verbose_name = '精算ログ'
        verbose_name_plural = '精算ログ'
        ordering = ['-create_ymd', '-settle_id']


class T_Assets(models.Model):
    """固定資産テーブル（Accessシステム連携 v_assets ビュー相当）"""

    # ── 識別 ──────────────────────────────────────────────────────────────
    asset_no                       = models.CharField("資産NO",              max_length=13, primary_key=True)

    # ── 科目・部門 ────────────────────────────────────────────────────────
    account_cd                     = models.CharField("科目コード",           max_length=2,  null=True, blank=True)
    account_name                   = models.CharField("科目名",               max_length=30, null=True, blank=True)
    bumon_cd                       = models.CharField("部門コード",           max_length=6,  null=True, blank=True)
    bumon_name                     = models.CharField("部門名",               max_length=30, null=True, blank=True)
    accounting_bumon_cd            = models.CharField("会計用部門コード",     max_length=8,  null=True, blank=True)

    # ── 資産名 ────────────────────────────────────────────────────────────
    asset_name1                    = models.CharField("資産名１",             max_length=60, null=True, blank=True)
    asset_name2                    = models.CharField("資産名２",             max_length=60, null=True, blank=True)

    # ── 構造細目 ──────────────────────────────────────────────────────────
    structure_cd                   = models.CharField("構造細目コード",       max_length=5,  null=True, blank=True)
    structure_name                 = models.CharField("構造名",               max_length=30, null=True, blank=True)
    detail_name                    = models.CharField("細目名",               max_length=30, null=True, blank=True)

    # ── 配賦 ──────────────────────────────────────────────────────────────
    alloc_kbn                      = models.CharField("部門配賦区分",         max_length=1,  null=True, blank=True)
    alloc_rate_cd                  = models.CharField("配賦率コード",         max_length=12, null=True, blank=True)

    # ── 数量・単位・耐用年数 ──────────────────────────────────────────────
    quantity                       = models.SmallIntegerField("個数",         null=True, blank=True)
    unit                           = models.CharField("単位",                 max_length=4,  null=True, blank=True)
    useful_life                    = models.DecimalField("耐用年数",          max_digits=5, decimal_places=2, null=True, blank=True)

    # ── 日付 ──────────────────────────────────────────────────────────────
    depreciation_start_date        = models.DateTimeField("償却開始日",       null=True, blank=True)
    acquisition_date               = models.DateTimeField("取得日",           null=True, blank=True)
    transfer_date                  = models.DateTimeField("異動増日付",       null=True, blank=True)
    installation_date              = models.DateTimeField("設置日",           null=True, blank=True)
    disposal_date                  = models.DateTimeField("除却日",           null=True, blank=True)
    registration_date              = models.DateTimeField("固定登録日",       null=True, blank=True)
    disposal_registration_date     = models.DateTimeField("除却登録日",       null=True, blank=True)
    transfer_registration_date     = models.DateTimeField("異動登録日",       null=True, blank=True)
    special_registration_date      = models.DateTimeField("特割登録日",       null=True, blank=True)
    depreciation_stop_start_date   = models.DateTimeField("償却停止開始日",   null=True, blank=True)
    depreciation_stop_end_date     = models.DateTimeField("償却停止終了日",   null=True, blank=True)
    straight_line_switch_date      = models.DateTimeField("定額切換日",       null=True, blank=True)

    # ── 金額（CURRENCY = decimal 18,4） ───────────────────────────────────
    acquisition_amount             = models.DecimalField("取得価額",          max_digits=18, decimal_places=4, null=True, blank=True)
    beginning_amount               = models.DecimalField("期首価額",          max_digits=18, decimal_places=4, null=True, blank=True)
    beginning_depreciation_diff    = models.DecimalField("期首償却過不足額",  max_digits=18, decimal_places=4, null=True, blank=True)
    residual_amount                = models.DecimalField("残存価額",          max_digits=18, decimal_places=4, null=True, blank=True)
    current_optional_depreciation  = models.DecimalField("当期任意償却額",    max_digits=18, decimal_places=4, null=True, blank=True)
    compression_reserve            = models.DecimalField("圧縮引当金",        max_digits=18, decimal_places=4, null=True, blank=True)
    beginning_adjustment           = models.DecimalField("期首価額調整額",    max_digits=18, decimal_places=4, null=True, blank=True)
    depreciation_limit             = models.DecimalField("償却可能限度額",    max_digits=18, decimal_places=4, null=True, blank=True)
    disposal_amount                = models.DecimalField("処分価額",          max_digits=18, decimal_places=4, null=True, blank=True)
    special_depreciation_amount    = models.DecimalField("特別償却額",        max_digits=18, decimal_places=4, null=True, blank=True)
    extra_depreciation_amount      = models.DecimalField("割増償却額",        max_digits=18, decimal_places=4, null=True, blank=True)
    prev_year_book_amount          = models.DecimalField("前年申告帳簿価額",  max_digits=18, decimal_places=4, null=True, blank=True)
    prev_year_assessed_amount      = models.DecimalField("前年申告評価額",    max_digits=18, decimal_places=4, null=True, blank=True)
    switch_book_amount             = models.DecimalField("切換時帳簿価額",    max_digits=18, decimal_places=4, null=True, blank=True)
    post_switch_annual_depreciation= models.DecimalField("切換後年償却額",    max_digits=18, decimal_places=4, null=True, blank=True)

    # ── フラグ（BIT） ─────────────────────────────────────────────────────
    current_optional_kbn           = models.SmallIntegerField("当期任意償却区分",  null=True, blank=True)
    special_rate_input_kbn         = models.SmallIntegerField("特例率入力区分",    null=True, blank=True)

    # ── 区分・コード ──────────────────────────────────────────────────────
    collateral_kbn                 = models.CharField("担保資産区分",         max_length=1,  null=True, blank=True)
    special_depreciation_kbn       = models.CharField("特別償却計算区分",     max_length=1,  null=True, blank=True)
    extra_depreciation_kbn         = models.CharField("割増償却計算区分",     max_length=1,  null=True, blank=True)
    tax_target_kbn                 = models.CharField("納税対象区分",         max_length=1,  null=True, blank=True)
    increase_reason                = models.CharField("増加事由",             max_length=1,  null=True, blank=True)
    disposal_kbn                   = models.CharField("除却区分",             max_length=1,  null=True, blank=True)
    decrease_kbn                   = models.CharField("減少区分",             max_length=1,  null=True, blank=True)

    # ── 設置場所 ──────────────────────────────────────────────────────────
    location_cd                    = models.CharField("設置場所コード",       max_length=6,  null=True, blank=True)
    location_name                  = models.CharField("設置場所名",           max_length=30, null=True, blank=True)
    city_cd                        = models.CharField("市区町村コード",       max_length=6,  null=True, blank=True)
    city_name                      = models.CharField("市区町村名",           max_length=30, null=True, blank=True)

    # ── 特例率 ────────────────────────────────────────────────────────────
    special_rate_numerator         = models.SmallIntegerField("特例率分子",   null=True, blank=True)
    special_rate_denominator       = models.SmallIntegerField("特例率分母",   null=True, blank=True)

    # ── その他参照 ────────────────────────────────────────────────────────
    source_asset_no                = models.CharField("異動元資産NO",         max_length=12, null=True, blank=True)
    supplier_cd                    = models.CharField("購入先コード",         max_length=10, null=True, blank=True)
    partial_expansion_asset_cd     = models.CharField("一部増設元資産コード", max_length=12, null=True, blank=True)
    ringi_no                       = models.CharField("稟議NO",              max_length=30, null=True, blank=True)
    manager                        = models.CharField("管理者",               max_length=30, null=True, blank=True)
    memo1                          = models.CharField("メモ欄",               max_length=40, null=True, blank=True)
    memo2                          = models.CharField("メモ欄２",             max_length=40, null=True, blank=True)
    model_name                     = models.CharField("モデル",               max_length=70, null=True, blank=True)
    serial_no                      = models.CharField("シリアルNO",          max_length=40, null=True, blank=True)
    physical_inventory_result      = models.CharField("実地調査結果",         max_length=40, null=True, blank=True)

    def __str__(self):
        return f"{self.asset_no} {self.asset_name1}"

    class Meta:
        db_table = 'T_ASSETS'
        verbose_name = '固定資産'
        verbose_name_plural = '固定資産'
        ordering = ['asset_no']


# 少額資産台帳
class T_AssetsLowValue(models.Model):
    """少額資産テーブル"""

    low_value_asset_no             = models.CharField("小額資産番号",         max_length=13, primary_key=True)
    maker_name                     = models.CharField("メーカー名",           max_length=50, null=True, blank=True)
    item_name                      = models.CharField("品名",                 max_length=100, null=True, blank=True)
    model_no                       = models.CharField("品番",                 max_length=50, null=True, blank=True)
    serial_no                      = models.CharField("製造番号",             max_length=50, null=True, blank=True)
    purpose                        = models.CharField("用途",                 max_length=100, null=True, blank=True)
    acquisition_price              = models.DecimalField("取得価格",          max_digits=18, decimal_places=4, null=True, blank=True)
    acquisition_date               = models.DateTimeField("年月日",           null=True, blank=True)
    bumon_cd                       = models.CharField("部門コード",           max_length=10, null=True, blank=True)
    bumon_name                     = models.CharField("部門名",               max_length=50, null=True, blank=True)
    location_cd                    = models.CharField("設置場所コード",       max_length=10, null=True, blank=True)
    location_name                  = models.CharField("設置場所名",           max_length=50, null=True, blank=True)
    cre_date                       = models.DateTimeField("作成日",           auto_now_add=True)
    up_date                        = models.DateTimeField("更新日",           auto_now=True)

    def __str__(self):
        return f"{self.low_value_asset_no} {self.item_name}"

    class Meta:
        db_table = 't_assets_low_value'
        verbose_name = '少額資産'
        verbose_name_plural = '少額資産'
        ordering = ['low_value_asset_no']


# 固定資産同期キュー（Web編集 → 本物MDBへのPush待ち）
class T_AssetsSyncQueue(models.Model):
    OPERATION_CHOICES = [('insert', '新規登録'), ('update', '更新')]
    STATUS_CHOICES = [('pending', '未送信'), ('done', '送信済'), ('error', 'エラー')]

    queue_id = models.AutoField("キューID", primary_key=True)
    asset_no = models.CharField("資産NO", max_length=13)
    operation = models.CharField("操作", max_length=10, choices=OPERATION_CHOICES)
    payload = models.JSONField("変更内容")
    status = models.CharField("状態", max_length=10, choices=STATUS_CHOICES, default='pending')
    error_msg = models.CharField("エラー内容", max_length=500, blank=True, default='')
    created_by = models.ForeignKey(
        M_User, to_field='man_number', db_column='created_by',
        on_delete=models.PROTECT, verbose_name="登録者",
    )
    created_at = models.DateTimeField("登録日時", auto_now_add=True)
    processed_at = models.DateTimeField("処理日時", null=True, blank=True)

    def __str__(self):
        return f"{self.asset_no} ({self.get_operation_display()}/{self.get_status_display()})"

    class Meta:
        db_table = 't_assets_sync_queue'
        verbose_name = '固定資産同期キュー'
        verbose_name_plural = '固定資産同期キュー'
        ordering = ['-created_at']


# 換算為替レートマスタ
class M_ExchangeRate(models.Model):
    keijo_ym      = models.CharField("計上年月", max_length=6)
    tsuka_cd      = models.CharField("通貨コード", max_length=3)
    exchange_rate = models.DecimalField("換算レート", max_digits=5, decimal_places=2)

    class Meta:
        db_table = 'M_ExchangeRate'
        unique_together = [('keijo_ym', 'tsuka_cd')]
        verbose_name = '換算為替レート'
        verbose_name_plural = '換算為替レート'


# ── GSESSION (旧グループウェア) 参照データ ─────────────────────────────
# tmp/gs2db.h2.db から deploy/gs2db_sync/extract_gs2db.py + import_gs2db
# コマンドで取り込む、参照専用の独立テーブル群。既存M_/T_系とは紐付けない。

class GS_Ringi(models.Model):
    """稟議データ本体（旧GSESSIONのRNG_RNDATAより参照専用インポート）"""

    rng_sid        = models.IntegerField("旧稟議SID", primary_key=True)
    rng_title      = models.CharField("件名", max_length=100)
    rng_makedate   = models.DateTimeField("作成日時")
    rng_applicate  = models.IntegerField("申請者旧USR_SID", null=True, blank=True)
    rng_appldate   = models.DateTimeField("申請日時", null=True, blank=True)
    rng_status     = models.IntegerField("ステータス")
    rng_compflg    = models.IntegerField("完了フラグ")
    rng_admcomment = models.CharField("管理者コメント", max_length=300, null=True, blank=True)
    rng_auid       = models.IntegerField("作成者旧USR_SID")
    rng_adate      = models.DateTimeField("作成日時(監査)")
    rng_euid       = models.IntegerField("更新者旧USR_SID")
    rng_edate      = models.DateTimeField("更新日時(監査)")
    rng_id         = models.CharField("表示用ID", max_length=120, null=True, blank=True)
    rtp_sid        = models.IntegerField("テンプレート旧SID")
    rtp_ver        = models.IntegerField("テンプレートバージョン")
    rct_ver        = models.IntegerField("カテゴリバージョン", default=0)

    def __str__(self):
        return f"{self.rng_sid} {self.rng_title}"

    class Meta:
        db_table = 'GS_RINGI'
        verbose_name = '旧稟議データ(GSESSION)'
        verbose_name_plural = '旧稟議データ(GSESSION)'
        ordering = ['-rng_sid']


class GS_Usr(models.Model):
    """ユーザー参照データ（旧GSESSIONのCMN_USRM+CMN_USRM_INFより参照専用インポート）

    パスワードハッシュ(USR_PSWD)はセキュリティ上の理由で取り込まない。
    """

    usr_sid           = models.IntegerField("旧ユーザーSID", primary_key=True)
    usr_lgid           = models.CharField("ログインID", max_length=256)
    usr_jkbn           = models.IntegerField("在籍区分")
    usi_sei            = models.CharField("姓", max_length=30, null=True, blank=True)
    usi_mei            = models.CharField("名", max_length=30, null=True, blank=True)
    usi_sei_kn         = models.CharField("姓カナ", max_length=60, null=True, blank=True)
    usi_mei_kn         = models.CharField("名カナ", max_length=60, null=True, blank=True)
    usi_syain_no       = models.CharField("社員番号", max_length=20, null=True, blank=True)
    usi_syozoku        = models.CharField("所属名", max_length=60, null=True, blank=True)
    usi_yakusyoku      = models.CharField("役職名", max_length=30, null=True, blank=True)
    pos_sid            = models.IntegerField("旧役職SID", null=True, blank=True)
    usi_entrance_date  = models.DateTimeField("入社日", null=True, blank=True)

    def __str__(self):
        return f"{self.usr_sid} {self.usi_sei}{self.usi_mei}"

    class Meta:
        db_table = 'GS_USR'
        verbose_name = '旧ユーザー(GSESSION)'
        verbose_name_plural = '旧ユーザー(GSESSION)'
        ordering = ['usr_sid']


class GS_Group(models.Model):
    """組織・グループマスタ（旧GSESSIONのCMN_GROUPMより参照専用インポート）"""

    grp_sid     = models.IntegerField("旧グループSID", primary_key=True)
    grp_id      = models.CharField("グループID", max_length=50)
    grp_name    = models.CharField("グループ名", max_length=50, null=True, blank=True)
    grp_name_kn = models.CharField("グループ名カナ", max_length=75, null=True, blank=True)
    grp_comment = models.CharField("コメント", max_length=1000, null=True, blank=True)
    grp_auid    = models.IntegerField("作成者旧USR_SID")
    grp_adate   = models.DateTimeField("作成日時")
    grp_euid    = models.IntegerField("更新者旧USR_SID")
    grp_edate   = models.DateTimeField("更新日時")
    grp_sort    = models.IntegerField("表示順")
    grp_jkbn    = models.IntegerField("状態区分")

    def __str__(self):
        return f"{self.grp_sid} {self.grp_name}"

    class Meta:
        db_table = 'GS_GROUP'
        verbose_name = '旧組織グループ(GSESSION)'
        verbose_name_plural = '旧組織グループ(GSESSION)'
        ordering = ['grp_sort', 'grp_sid']


class GS_Belong(models.Model):
    """所属（グループ-ユーザーの紐付け。旧GSESSIONのCMN_BELONGMより参照専用インポート）"""

    grp_sid    = models.IntegerField("旧グループSID")
    usr_sid    = models.IntegerField("旧ユーザーSID")
    beg_auid   = models.IntegerField("作成者旧USR_SID")
    beg_adate  = models.DateTimeField("作成日時")
    beg_euid   = models.IntegerField("更新者旧USR_SID")
    beg_edate  = models.DateTimeField("更新日時")
    beg_defgrp = models.IntegerField("デフォルトグループ区分")
    beg_grpkbn = models.IntegerField("グループ区分", null=True, blank=True)

    def __str__(self):
        return f"grp={self.grp_sid} usr={self.usr_sid}"

    class Meta:
        db_table = 'GS_BELONG'
        verbose_name = '旧所属(GSESSION)'
        verbose_name_plural = '旧所属(GSESSION)'
        unique_together = [('grp_sid', 'usr_sid', 'beg_grpkbn')]


class GS_Position(models.Model):
    """役職マスタ（旧GSESSIONのCMN_POSITIONより参照専用インポート）"""

    pos_sid   = models.IntegerField("旧役職SID", primary_key=True)
    pos_code  = models.CharField("役職コード", max_length=15)
    pos_name  = models.CharField("役職名", max_length=30)
    pos_biko  = models.CharField("備考", max_length=300, blank=True)
    pos_sort  = models.IntegerField("表示順")
    pos_auid  = models.IntegerField("作成者旧USR_SID")
    pos_adate = models.DateTimeField("作成日時")
    pos_euid  = models.IntegerField("更新者旧USR_SID")
    pos_edate = models.DateTimeField("更新日時")

    def __str__(self):
        return f"{self.pos_sid} {self.pos_name}"

    class Meta:
        db_table = 'GS_POSITION'
        verbose_name = '旧役職(GSESSION)'
        verbose_name_plural = '旧役職(GSESSION)'
        ordering = ['pos_sort', 'pos_sid']

