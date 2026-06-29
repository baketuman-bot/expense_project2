from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0080_add_m_excheng_rate'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='m_exchengrate',
            unique_together=set(),
        ),
        migrations.RenameModel(
            old_name='M_ExchengRate',
            new_name='M_ExchangeRate',
        ),
        migrations.RenameField(
            model_name='m_exchangerate',
            old_name='keijyo_ym',
            new_name='keijo_ym',
        ),
        migrations.RenameField(
            model_name='m_exchangerate',
            old_name='exchenge_rate',
            new_name='exchange_rate',
        ),
        migrations.AlterUniqueTogether(
            name='m_exchangerate',
            unique_together={('keijo_ym', 'tsuka_cd')},
        ),
    ]
