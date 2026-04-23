"""Add pay_kbn to T_Document so the payment method persists across edits."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0040_m_status_order_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='t_document',
            name='pay_kbn',
            field=models.CharField(
                blank=True,
                db_column='pay_kbn',
                max_length=2,
                null=True,
                verbose_name='精算方法',
            ),
        ),
    ]
