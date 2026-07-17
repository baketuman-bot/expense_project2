# 全テーブルのコレーションを utf8mb4_0900_ai_ci に統一する。
# 2026-07-17 にDB既定・一部テーブルを手動で utf8mb4_0900_ai_ci へ変更したのに合わせ、
# 残っていた utf8mb3_general_ci / utf8mb4_unicode_ci のテーブルを一括変換する。
# 実行時点で utf8mb4_0900_ai_ci 以外のテーブルのみ対象とするため冪等。
from django.db import migrations

TARGET_COLLATION = 'utf8mb4_0900_ai_ci'


def unify_collation(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT TABLE_NAME FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_TYPE = 'BASE TABLE'
              AND TABLE_COLLATION <> %s
            """,
            [TARGET_COLLATION],
        )
        tables = [row[0] for row in cursor.fetchall()]
        if not tables:
            return
        # 文字列カラム同士のFK（例: t_documents.man_number → m_user.man_number）が
        # あるため、変換順序に依存しないよう一時的にFKチェックを無効化する
        cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        try:
            for table in tables:
                cursor.execute(
                    f"ALTER TABLE `{table}` "
                    f"CONVERT TO CHARACTER SET utf8mb4 COLLATE {TARGET_COLLATION}"
                )
        finally:
            cursor.execute("SET FOREIGN_KEY_CHECKS=1")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('expenses', '0113_v_documents_add_rng_title'),
    ]

    operations = [
        migrations.RunPython(unify_collation, migrations.RunPython.noop),
    ]
