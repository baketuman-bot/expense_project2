"""Add order_by to M_Status and seed initial values."""
from django.db import migrations, models


ORDER_MAP = {
    'DRAFT':    10,
    'INPRO':    20,
    'RETURNED': 30,
    'REJECTED': 40,
    'APPROVED': 50,
    'FNS':      60,
    'PAY':      70,
    'BAN':      71,
    'SAL':      72,
    'CANCEL':   90,
}


def forward(apps, schema_editor):
    M_Status = apps.get_model('expenses', 'M_Status')
    for cd, order in ORDER_MAP.items():
        M_Status.objects.filter(status_cd=cd).update(order_by=order)


def backward(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0039_merge_onpro_wfinprogress_into_inpro'),
    ]

    operations = [
        migrations.AddField(
            model_name='m_status',
            name='order_by',
            field=models.IntegerField(default=100, verbose_name='表示順'),
        ),
        migrations.AlterModelOptions(
            name='m_status',
            options={'ordering': ['order_by', 'status_cd']},
        ),
        migrations.RunPython(forward, backward),
    ]
