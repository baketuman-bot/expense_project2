from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0074_add_m_account_sub'),
    ]

    operations = [
        # M_Item に content3, order_by を追加
        migrations.AddField(
            model_name='m_item',
            name='content3',
            field=models.CharField(blank=True, max_length=30, verbose_name='内容3'),
        ),
        migrations.AddField(
            model_name='m_item',
            name='order_by',
            field=models.IntegerField(blank=True, null=True, verbose_name='表示順'),
        ),
        # M_Bumon に consumption_tax_kbn を追加
        migrations.AddField(
            model_name='m_bumon',
            name='consumption_tax_kbn',
            field=models.SmallIntegerField(blank=True, null=True, verbose_name='消費税区分'),
        ),
    ]
