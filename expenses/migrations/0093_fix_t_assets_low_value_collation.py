from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0092_add_t_assets_low_value'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "SET FOREIGN_KEY_CHECKS=0;",
                "ALTER TABLE t_assets_low_value CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
                "SET FOREIGN_KEY_CHECKS=1;",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
