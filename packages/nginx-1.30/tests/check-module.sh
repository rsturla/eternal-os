#!/usr/bin/env bash
set -euo pipefail

module=$1
case "$module" in
  stream) object=ngx_stream_module.so ;;
  mail) object=ngx_mail_module.so ;;
  image-filter) object=ngx_http_image_filter_module.so ;;
  xslt) object=ngx_http_xslt_filter_module.so ;;
  perl) object=ngx_http_perl_module.so ;;
  *) exit 1 ;;
esac
for directory in /usr/lib64/nginx/modules /usr/lib/nginx/modules; do
  test -f "$directory/$object" && break
done
test -f "$directory/$object"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cat > "$work/nginx.conf" <<EOF
load_module $directory/$object;
pid $work/nginx.pid;
error_log stderr;
events {}
http {
    access_log off;
    client_body_temp_path $work/client_temp;
    proxy_temp_path $work/proxy_temp;
    fastcgi_temp_path $work/fastcgi_temp;
    uwsgi_temp_path $work/uwsgi_temp;
    scgi_temp_path $work/scgi_temp;
EOF
case "$module" in
  image-filter) echo 'server { listen 8080; location / { image_filter size; } }' ;;
  xslt) echo 'server { listen 8080; location / { xslt_types application/xml; } }' ;;
  perl) cat <<'EOF'
    perl_set $module_value 'sub { return "perl module works"; }';
    server { listen 8080; location / { return 200 $module_value; } }
EOF
    ;;
esac >> "$work/nginx.conf"
echo '}' >> "$work/nginx.conf"
case "$module" in
  stream) echo 'stream { server { listen 8081; proxy_pass 127.0.0.1:8082; } }' ;;
  mail) echo 'mail { auth_http 127.0.0.1:8082/auth; server { listen 8143; protocol imap; } }' ;;
esac >> "$work/nginx.conf"
nginx -t -e stderr -c "$work/nginx.conf"
