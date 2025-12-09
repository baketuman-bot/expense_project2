# Apache deployment (mod_wsgi)

## Files
- `expense_project2.conf`: vhost config to place at `/etc/apache2/sites-available/expense_project2.conf`.

## Steps
1. Ensure packages
   - Ubuntu/Debian example:
     - `sudo apt install apache2 libapache2-mod-wsgi-py3`
2. Python venv and deps
   - Already present at `/home/idc_user/expense_project2/venv`.
   - Install deps if needed: `source venv/bin/activate && pip install -r requirements.txt`
3. Static files
   - In settings.py, `STATIC_ROOT` is set to `BASE_DIR/static`.
   - Collect: `python manage.py collectstatic`
4. Enable site
   - Copy config: `sudo cp apache/expense_project2.conf /etc/apache2/sites-available/`
   - Enable: `sudo a2ensite expense_project2.conf`
   - Enable mod_wsgi (once): `sudo a2enmod wsgi`
   - Reload: `sudo systemctl reload apache2`
5. Test
   - Open: `http://172.16.100.149/`
   - Logs: `sudo tail -f /var/log/apache2/expense_project2_error.log`

## Notes
- If you switch venv path, update `python-home` in the vhost.
- Make sure `/home/idc_user/expense_project2/static` and `media` are readable by Apache user.
- For HTTPS, use certbot: `sudo certbot --apache -d <domain>`.
