# Apache deployment

## Files
- `expense_project2.conf`: Linux Apache(mod_wsgi) vhost config to place at `/etc/apache2/sites-available/expense_project2.conf`.
- `expense_project2-proxy-windows.conf`: Windows Apache24 reverse-proxy vhost config to place at `C:\Apache24\conf\extra\expense_project2-proxy-windows.conf`.
- `httpd.conf-windows-snippet.txt`: Lines to enable in `C:\Apache24\conf\httpd.conf`.

## Option A: Windows Apache24 (recommended) -> reverse proxy to WSL/Linux Django
This workspace is Linux/WSL. Running `mod_wsgi` directly in Windows Apache is not practical, so use a reverse proxy.

1. Start Django backend on WSL/Linux
   - Recommended (production-ish):
     - `source .venv/bin/activate`
     - `export DEBUG=0`
     - `export SERVE_MEDIA=1`
     - `python manage.py collectstatic --noinput`
   - `gunicorn expense_project.wsgi:application --bind 0.0.0.0:8000`

2. Configure Windows Apache24
   - Copy `expense_project2-proxy-windows.conf` to `C:\Apache24\conf\extra\expense_project2-proxy-windows.conf`.
   - Apply module/include changes from `httpd.conf-windows-snippet.txt`.
   - Validate & restart from Windows:
     - `C:\Apache24\bin\httpd -t`
     - `C:\Apache24\bin\httpd -k restart`

3. Test
   - Open: `http://172.16.100.150/`
   - If it fails: check `C:\Apache24\logs\error.log` and `logs/expense_project2_error.log`.

    Backend reachability checks (important when you are behind a corporate proxy such as Squid):
    - From WSL/Linux:
       - `curl -I --noproxy '*' --max-time 5 http://127.0.0.1:8000/`
    - From Windows (bypass proxy explicitly; otherwise `curl` may go through Squid and you will NOT be testing localhost):
       - `curl.exe --noproxy "*" -I --max-time 5 http://127.0.0.1:8000/`
    - If `127.0.0.1:8000` fails on Windows but WSL is listening, try the WSL IP from Windows:
       - In WSL: `hostname -I`
       - In Windows: `curl.exe --noproxy "*" -I --max-time 5 http://<WSL_IP>:8000/`
       - If this works, update the ProxyPass target in `expense_project2-proxy-windows.conf` to use `<WSL_IP>`.

## Option B: Linux Apache (mod_wsgi)
## Steps
1. Ensure packages
   - Ubuntu/Debian example:
     - `sudo apt install apache2 libapache2-mod-wsgi-py3`
2. Python venv and deps
   - Already present at `/home/idc_user/expense_project2/.venv`.
   - Install deps if needed: `source .venv/bin/activate && pip install -r requirements.txt`
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

