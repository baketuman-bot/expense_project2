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

    def __str__(self):
        return self.status_name

    class Meta:
        db_table = 'm_status'


# ユーザーマスタ（AbstractUser拡張）
class M_User(AbstractUser):
    # Django 標準の username, password, email などに加えて独自フィールドを追加
    man_number = models.CharField("社員番号", max_length=20, unique=True)
    user_name = models.CharField("氏名", max_length=30)
    bumon_cd = models.ForeignKey(M_Bumon, verbose_name="部門", on_delete=models.PROTECT, null=True, blank=True)
    post_cd = models.ForeignKey(M_Post, verbose_name="役職", on_delete=models.PROTECT, null=True, blank=True)
    role = models.CharField("権限", max_length=20, choices=[
        ("employee", "従業員"),
        ("approver", "承認者"),
        ("accountant", "経理担当者"),
        ("final_approver", "経理承認者"),
    ], default="employee")

    def __str__(self):
        return self.user_name

    class Meta:
        db_table = 'm_user'


# 勘定科目マスタ
class M_Account(models.Model):
    account_cd = models.CharField("勘定科目コード", max_length=20, primary_key=True, default='DEFAULT')
    account_name = models.CharField("勘定科目名", max_length=100)

    def __str__(self):
        return self.account_name

    class Meta:
        db_table = 'm_account'


# 汎用項目マスタ
class M_Item(models.Model):
    data_kbn = models.CharField("データ区分", max_length=4, blank=True)
    key = models.CharField("キー", max_length=4, blank=True)
    content = models.CharField("内容", max_length=50, blank=True)
    content2 = models.CharField("内容2", max_length=50)

    class Meta:
        db_table = 'm_item'
        verbose_name = '汎用項目マスタ'
        verbose_name_plural = '汎用項目マスタ'
        constraints = [
            models.UniqueConstraint(fields=["data_kbn", "key"], name="uq_m_item_data_kbn_key"),
        ]

    def __str__(self):
        return f"{self.key} - {self.content}"


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


# 文書種別マスタ
class M_DocumentType(models.Model):
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

    def __str__(self):
        return self.document_type_name

    class Meta:
        db_table = 'm_document_types'
        verbose_name = '文書種別マスタ'
        verbose_name_plural = '文書種別マスタ'


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
    memo = models.TextField("メモ", null=True, blank=True)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

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
        amounts = self.contents.values_list('amount', flat=True)
        total = Decimal('0')
        for a in amounts:
            if a:
                total += Decimal(a)
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

    # 旧フィールド（receipt/receipt_thumbnail）廃止に伴い、サムネイル生成や save の上書きは不要

    def __str__(self):
        return f"{self.document_detail_id} - {self.purpose or ''}"

    class Meta:
        db_table = 't_documentcontents'
        verbose_name = '文書明細'
        verbose_name_plural = '文書明細'


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
        convert_from_path = _safe_import_pdf2image()
        if not self.file:
            return
        _, ext = os.path.splitext(self.file.name)
        ext = (ext or '').lower()
        if ext == '.pdf' and convert_from_path:
            try:
                pdf_path = os.path.join(settings.MEDIA_ROOT, self.file.name)
                pages = convert_from_path(pdf_path, first_page=1, last_page=1, fmt='jpeg')
                if pages:
                    img = pages[0]
                    img.thumbnail((400, 400))
                    thumb_io = io.BytesIO()
                    img.save(thumb_io, format='JPEG', quality=85)
                    orig = os.path.basename(self.file.name)
                    name, _ = os.path.splitext(orig)
                    target_path = attachment_thumbnail_upload_path(self, f"{name}_thumb.jpg")
                    self.thumbnail.save(target_path, ContentFile(thumb_io.getvalue()), save=False)
            except Exception:
                pass
        elif Image:
            try:
                img = Image.open(self.file)
                img.thumbnail((400, 400))
                thumb_io = io.BytesIO()
                img.save(thumb_io, format='JPEG', quality=85)
                orig = os.path.basename(self.file.name)
                name, _ = os.path.splitext(orig)
                target_path = attachment_thumbnail_upload_path(self, f"{name}_thumb.jpg")
                self.thumbnail.save(target_path, ContentFile(thumb_io.getvalue()), save=False)
            except Exception:
                pass

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
