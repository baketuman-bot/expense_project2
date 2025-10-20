from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.conf import settings
from expenses.models import T_DocumentContent, T_DocumentAttachment
import os

class Command(BaseCommand):
    help = "Migrate legacy single receipt files on T_DocumentContent into T_DocumentAttachment per detail."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Do not write changes, only report what would happen')
        parser.add_argument('--limit', type=int, default=None, help='Limit number of details to process')
        parser.add_argument('--start-id', type=int, default=None, help='Start from this document_detail_id (inclusive)')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']
        start_id = options['start_id']

        # Safety: confirm MEDIA_ROOT exists
        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if not media_root:
            raise CommandError('MEDIA_ROOT is not configured.')

        # Because model fields were removed, access legacy columns via values() to read paths if columns still exist in DB
        # Fallback: if columns are already dropped, nothing to migrate.
        legacy_fields = ['document_detail_id', 'document_id']
        # Try to include legacy columns if present
        possible_legacy_columns = ['receipt', 'receipt_thumbnail']

        # Build queryset selecting raw dicts; handle missing columns gracefully
        qs = T_DocumentContent.objects.all()
        if start_id:
            qs = qs.filter(document_detail_id__gte=start_id)
        qs = qs.order_by('document_detail_id')
        total = qs.count()
        if limit:
            qs = qs[:limit]

        processed = 0
        created = 0
        skipped = 0
        missing_files = 0
        self.stdout.write(f"Scanning {qs.count()} of {total} details...")

        # We will fetch raw rows to try to access legacy columns using cursor if needed
        from django.db import connection
        with connection.cursor() as cursor:
            table = T_DocumentContent._meta.db_table
            # discover existing columns
            cursor.execute(f"PRAGMA table_info({table})") if connection.vendor == 'sqlite' else cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = %s", [table])
            cols = [row[1] if connection.vendor == 'sqlite' else row[0] for row in cursor.fetchall()]
            has_receipt = 'receipt' in cols
            has_thumb = 'receipt_thumbnail' in cols

        if not has_receipt:
            self.stdout.write(self.style.WARNING('Legacy columns not found on table; nothing to migrate.'))
            return

        # Iterate details and read legacy path using raw SQL per row to avoid model attribute errors
        from django.db import connection
        table = T_DocumentContent._meta.db_table
        pk_name = 'document_detail_id'
        select_cols = [pk_name, 'document_id', 'receipt'] + (['receipt_thumbnail'] if has_thumb else [])
        where = ''
        params = []
        placeholder = '?' if connection.vendor == 'sqlite' else '%s'
        if start_id:
            where = f"WHERE {pk_name} >= {placeholder}"
            params.append(start_id)
        order = f"ORDER BY {pk_name} ASC"
        limit_clause = f"LIMIT {int(limit)}" if limit else ''
        sql = f"SELECT {', '.join(select_cols)} FROM {table} {where} {order} {limit_clause}".strip()

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        # Map column indexes
        col_index = {name: idx for idx, name in enumerate(select_cols)}

        @transaction.atomic
        def migrate_rows(_rows):
            nonlocal created, skipped, missing_files, processed
            for row in _rows:
                processed += 1
                detail_id = row[col_index[pk_name]]
                receipt_relpath = row[col_index['receipt']]
                if not receipt_relpath:
                    skipped += 1
                    continue
                # Ensure no duplicate attachment exists for same source path
                try:
                    detail = T_DocumentContent.objects.get(pk=detail_id)
                except T_DocumentContent.DoesNotExist:
                    skipped += 1
                    continue
                # If already migrated (same filename present), skip by basename
                old_base = os.path.basename(receipt_relpath)
                existing_files = list(detail.attachments.values_list('file', flat=True))
                if any(os.path.basename(p or '') == old_base for p in existing_files):
                    skipped += 1
                    continue
                # File existence check
                abs_path = os.path.join(media_root, receipt_relpath)
                if not os.path.exists(abs_path):
                    missing_files += 1
                    continue
                if dry_run:
                    self.stdout.write(f"Would create attachment for detail {detail_id}: {receipt_relpath}")
                    created += 1
                    continue
                # Create attachment (thumbnail will be generated by model if possible)
                from django.core.files.base import File
                with open(abs_path, 'rb') as f:
                    django_file = File(f)
                    att = T_DocumentAttachment(detail=detail)
                    # Save with original basename to new upload_to path
                    basename = os.path.basename(receipt_relpath)
                    att.file.save(basename, django_file, save=True)
                created += 1

        migrate_rows(rows)

        self.stdout.write(self.style.SUCCESS(
            f"Done. processed={processed}, created={created}, skipped={skipped}, missing_files={missing_files}"
        ))
