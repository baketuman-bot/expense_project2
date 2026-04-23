"""Consolidate duplicate M_Status codes into canonical ones.

Mapping applied:
    APP         -> APPROVED
    DRA         -> DRAFT
    DRF         -> DRAFT
    IN_PROGRESS -> WF_INPROGRESS
    REJ         -> REJECTED
    RET         -> RETURNED
    SUB         -> SUBMITTED
    WAITING     -> WF_INPROGRESS

Stays: APPROVED, BAN, CAN, COMPLETED, DRAFT, FNS, PAY, REJECTED,
       RETURNED, SAL, SUBMITTED, WF_INPROGRESS

Updates all FK / CharField references on T_Document.status_cd,
T_WorkflowInstance.status, T_WorkflowAction.action_status,
T_DocumentApprover.status, then deletes the obsolete M_Status rows.
"""
from django.db import migrations


MAPPING = {
    'APP': 'APPROVED',
    'DRA': 'DRAFT',
    'DRF': 'DRAFT',
    'IN_PROGRESS': 'WF_INPROGRESS',
    'REJ': 'REJECTED',
    'RET': 'RETURNED',
    'SUB': 'SUBMITTED',
    'WAITING': 'WF_INPROGRESS',
}

TARGET_DEFAULTS = {
    'APPROVED': ('承認済', 'APPROVED'),
    'DRAFT': ('下書き', None),
    'WF_INPROGRESS': ('進行中', None),
    'REJECTED': ('却下', 'REJECTED'),
    'RETURNED': ('差戻し', 'RETURNED'),
    'SUBMITTED': ('申請中', None),
}


def forward(apps, schema_editor):
    M_Status = apps.get_model('expenses', 'M_Status')
    T_Document = apps.get_model('expenses', 'T_Document')
    T_WorkflowInstance = apps.get_model('expenses', 'T_WorkflowInstance')
    T_WorkflowAction = apps.get_model('expenses', 'T_WorkflowAction')
    T_DocumentApprover = apps.get_model('expenses', 'T_DocumentApprover')

    for cd, (name, action) in TARGET_DEFAULTS.items():
        # Do not overwrite existing records' human-readable names.
        M_Status.objects.get_or_create(
            status_cd=cd,
            defaults={'status_name': name, 'action_name': action},
        )

    for old, new in MAPPING.items():
        T_Document.objects.filter(status_cd_id=old).update(status_cd_id=new)
        T_WorkflowInstance.objects.filter(status_id=old).update(status_id=new)
        T_WorkflowAction.objects.filter(action_status_id=old).update(action_status_id=new)
        T_DocumentApprover.objects.filter(status=old).update(status=new)

    M_Status.objects.filter(status_cd__in=list(MAPPING.keys())).delete()


def backward(apps, schema_editor):
    # Irreversible: old codes were lossy merges (e.g. IN_PROGRESS/WAITING -> WF_INPROGRESS)
    raise RuntimeError("Irreversible: cannot split merged status codes back.")


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0036_add_bumon_scope_to_documenttype'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
