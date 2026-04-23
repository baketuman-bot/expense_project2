"""Rename SUBMITTED -> ONPRO, CAN -> CANCEL, remove unused COMPLETED."""
from django.db import migrations


MAPPING = {
    'SUBMITTED': 'ONPRO',
    'CAN': 'CANCEL',
}

TARGET_DEFAULTS = {
    'ONPRO': ('申請中', None),
    'CANCEL': ('取り下げ', '取消し'),
}

TO_DELETE = ['SUBMITTED', 'CAN', 'COMPLETED']


def forward(apps, schema_editor):
    M_Status = apps.get_model('expenses', 'M_Status')
    T_Document = apps.get_model('expenses', 'T_Document')
    T_WorkflowInstance = apps.get_model('expenses', 'T_WorkflowInstance')
    T_WorkflowAction = apps.get_model('expenses', 'T_WorkflowAction')
    T_DocumentApprover = apps.get_model('expenses', 'T_DocumentApprover')

    for cd, (name, action) in TARGET_DEFAULTS.items():
        M_Status.objects.get_or_create(
            status_cd=cd,
            defaults={'status_name': name, 'action_name': action},
        )

    for old, new in MAPPING.items():
        T_Document.objects.filter(status_cd_id=old).update(status_cd_id=new)
        T_WorkflowInstance.objects.filter(status_id=old).update(status_id=new)
        T_WorkflowAction.objects.filter(action_status_id=old).update(action_status_id=new)
        T_DocumentApprover.objects.filter(status=old).update(status=new)

    M_Status.objects.filter(status_cd__in=TO_DELETE).delete()


def backward(apps, schema_editor):
    raise RuntimeError("Irreversible: renamed/removed status codes cannot be restored automatically.")


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0037_consolidate_m_status_codes'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
