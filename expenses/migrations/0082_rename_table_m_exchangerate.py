from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0081_fix_m_exchangerate'),
    ]

    operations = [
        migrations.AlterModelTable(
            name='m_exchangerate',
            table='M_ExchangeRate',
        ),
    ]
