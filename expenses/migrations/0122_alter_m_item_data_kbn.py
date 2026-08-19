# Generated migration to extend data_kbn field to accommodate 'CHN_ADJRATE'

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0121_china_invoice'),
    ]

    operations = [
        migrations.AlterField(
            model_name='m_item',
            name='data_kbn',
            field=models.CharField(blank=True, max_length=20, verbose_name='データ区分'),
        ),
    ]
