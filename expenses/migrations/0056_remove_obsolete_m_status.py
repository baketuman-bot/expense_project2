from django.db import migrations

# 旧マイグレーション時の残骸として残っていた不要な status_cd を削除する。
# いずれも T_Document / T_WorkflowAction / コードのどこからも参照されていない。
#
# 存続させるもの（7 + 3 = 10 件）:
#   DRAFT, INPRO, APPROVED, FNS, REJECTED, RETURNED, CANCEL  ← ワークフローで使用
#   PAY, SAL, BAN                                            ← ユーザー指定で存続

TO_DELETE = [
    'APP',          # → APPROVED に統合 (migration 0037)
    'CAN',          # → CANCEL に統合 (migration 0038)
    'COMPLETED',    # migration 0038 で削除予定だった残骸
    'DRA',          # → DRAFT に統合 (migration 0037)
    'DRF',          # → DRAFT に統合 (migration 0037)
    'IN_PROGRESS',  # → WF_INPROGRESS に統合 (migration 0037)
    'REJ',          # → REJECTED に統合 (migration 0037)
    'RET',          # → RETURNED に統合 (migration 0037)
    'SUB',          # 旧コード、SUBMITTED を経て廃止
    'SUBMITTED',    # migration 0038 で削除予定だった残骸
    'WAITING',      # → WF_INPROGRESS に統合 (migration 0037)
    'WF_INPROGRESS', # → INPRO に統合 (migration 0039)
]


def remove_obsolete_statuses(apps, schema_editor):
    M_Status = apps.get_model('expenses', 'M_Status')
    deleted = M_Status.objects.filter(status_cd__in=TO_DELETE).delete()
    print(f'\n  削除件数: {deleted[0]} 件')


def restore_obsolete_statuses(apps, schema_editor):
    # ロールバック用: 旧レコードを再挿入
    M_Status = apps.get_model('expenses', 'M_Status')
    restore_data = [
        ('APP',          '回覧中',             None),
        ('CAN',          '取り下げ',           None),
        ('COMPLETED',    '完了',               None),
        ('DRA',          '下書き',             None),
        ('DRF',          '作成中',             None),
        ('IN_PROGRESS',  '進行中',             None),
        ('REJ',          '却下',               None),
        ('RET',          '差し戻し中',         None),
        ('SUB',          '申請中',             None),
        ('SUBMITTED',    '申請中',             None),
        ('WAITING',      '承認待ち',           None),
        ('WF_INPROGRESS','ワークフロー進行中',  None),
    ]
    for cd, name, action in restore_data:
        M_Status.objects.get_or_create(
            status_cd=cd,
            defaults={'status_name': name, 'action_name': action},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0055_add_settlement_fields'),
    ]

    operations = [
        migrations.RunPython(remove_obsolete_statuses, restore_obsolete_statuses),
    ]
