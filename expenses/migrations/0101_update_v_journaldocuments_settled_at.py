from django.db import migrations

from expenses.view_sqls import _V_JOURNALDOCUMENTS

_OLD_V_JOURNALDOCUMENTS = _V_JOURNALDOCUMENTS.replace(
    'COALESCE(DATE(vdc.settled_at), vdc.date) AS date,',
    'vdc.date,',
)


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0100_settled_at_help_text'),
    ]

    operations = [
        migrations.RunSQL(
            sql=_V_JOURNALDOCUMENTS,
            reverse_sql=_OLD_V_JOURNALDOCUMENTS,
        ),
    ]
