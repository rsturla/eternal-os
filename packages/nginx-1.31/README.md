# NGINX 1.31

The built-in HTTP features and the five upstream dynamic modules follow
[Wolfi's standard NGINX build](https://github.com/wolfi-dev/os/blob/0f03763ae7f9a08b009eccd935f97c8e473be1a2/nginx-mainline.yaml).
The web build profile selects Eternal's libxslt and libxml2 ABI.
OpenSSL build headers and the test CLI use generic capabilities. The web profile
selects the adopted stream; rpmx generates runtime requirements for its ABI.
The image module uses the Expat-backed in-tree fontconfig dependency.
Eternal supplies compiler hardening through `openssf-compiler-options`.
The recipe also enables PCRE JIT support.

The main RPM provides `nginx`. The 1.30 and 1.31 streams conflict because they
own the same command and configuration paths. Configuration stays in
`/etc/nginx`, runtime files use `/run`, and request buffers use
`/var/cache/nginx`. The default configuration sends logs to stdout and stderr.
Workers use the `nobody` account supplied by `setup`.

## Optional modules

The main RPM does not depend on or load any optional module. Each module RPM
requires the exact matching NGINX version and release.

| RPM | Module file |
| --- | --- |
| `nginx-1.31-mod-stream` | `ngx_stream_module.so` |
| `nginx-1.31-mod-mail` | `ngx_mail_module.so` |
| `nginx-1.31-mod-image-filter` | `ngx_http_image_filter_module.so` |
| `nginx-1.31-mod-xslt` | `ngx_http_xslt_filter_module.so` |
| `nginx-1.31-mod-perl` | `ngx_http_perl_module.so` |

After you install a module RPM, add its `load_module` directive at the top level
of `nginx.conf`, before the `events` and `http` blocks. For example, on x86_64:

```nginx
load_module /usr/lib64/nginx/modules/ngx_stream_module.so;
```

Use the module directory shown by `nginx -V` for other library layouts.
Run `nginx -t` before you reload the server. The Perl module uses Eternal's Perl 5.44 stream and keeps its Perl
files private under the NGINX library directory.

HTTP/3, WebDAV, and third-party modules are outside this initial package set.
The `-doc` RPM contains manuals and upstream configuration examples.
