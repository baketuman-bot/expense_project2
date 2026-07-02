from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0089_add_t_assets_sync_queue'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "SET FOREIGN_KEY_CHECKS=0;",
                "ALTER TABLE t_assets_sync_queue CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
                "SET FOREIGN_KEY_CHECKS=1;",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
