from django.db import migrations

from expenses.view_sqls import _V_JOURNALDOCUMENTS

_OLD_V_JOURNALDOCUMENTS = _V_JOURNALDOCUMENTS.replace(
    "  vdc.journal_tori_cd_cre,\n"
    "  vdc.journal_discription_cre,\n"
    "  vdc.settled_at\n"
    "FROM v_documentcontents vdc\n",
    "  vdc.journal_tori_cd_cre,\n"
    "  vdc.journal_discription_cre\n"
    "FROM v_documentcontents vdc\n",
)


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0101_update_v_journaldocuments_settled_at'),
    ]

    operations = [
        migrations.RunSQL(
            sql=_V_JOURNALDOCUMENTS,
            reverse_sql=_OLD_V_JOURNALDOCUMENTS,
        ),
    ]
