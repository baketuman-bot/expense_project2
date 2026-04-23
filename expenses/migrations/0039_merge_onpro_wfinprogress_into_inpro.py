"""Merge ONPRO + WF_INPROGRESS -> INPRO."""
from django.db import migrations


MAPPING = {
    'ONPRO': 'INPRO',
    'WF_INPROGRESS': 'INPRO',
}


def forward(apps, schema_editor):
    M_Status = apps.get_model('expenses', 'M_Status')
    T_Document = apps.get_model('expenses', 'T_Document')
    T_WorkflowInstance = apps.get_model('expenses', 'T_WorkflowInstance')
    T_WorkflowAction = apps.get_model('expenses', 'T_WorkflowAction')
    T_DocumentApprover = apps.get_model('expenses', 'T_DocumentApprover')

    M_Status.objects.get_or_create(
        status_cd='INPRO',
        defaults={'status_name': '申請中', 'action_name': None},
    )

    for old, new in MAPPING.items():
        T_Document.objects.filter(status_cd_id=old).update(status_cd_id=new)
        T_WorkflowInstance.objects.filter(status_id=old).update(status_id=new)
        T_WorkflowAction.objects.filter(action_status_id=old).update(action_status_id=new)
        T_DocumentApprover.objects.filter(status=old).update(status=new)

    M_Status.objects.filter(status_cd__in=list(MAPPING.keys())).delete()


def backward(apps, schema_editor):
    raise RuntimeError("Irreversible: ONPRO and WF_INPROGRESS were merged into INPRO.")


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0038_rename_submitted_can_remove_completed'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
