# Review Service (PHP + SQLite PDO, cổng 8005) chạy trên Apache + mod_php (thay cho php -S chỉ dùng khi phát triển).
# Build: docker build -t tdtu-food/review services/review
FROM php:8.4-apache

RUN cp "$PHP_INI_DIR/php.ini-production" "$PHP_INI_DIR/php.ini" \
 && printf 'expose_php = Off\nmemory_limit = 128M\npost_max_size = 1M\nupload_max_filesize = 1M\n' \
      > "$PHP_INI_DIR/conf.d/zz-tdtu.ini" \
 && a2enmod rewrite >/dev/null \
 && sed -ri 's/^Listen 80$/Listen 8005/' /etc/apache2/ports.conf \
 && sed -ri 's/^ServerTokens .*/ServerTokens Prod/; s/^ServerSignature .*/ServerSignature Off/' \
      /etc/apache2/conf-available/security.conf \
 && printf '%s\n' \
      '<VirtualHost *:8005>' \
      '  DocumentRoot /var/www/review/public' \
      '  <Directory /var/www/review/public>' \
      '    AllowOverride None' \
      '    Require all granted' \
      '    # Authorization (Bearer token) mặc định bị Apache ẩn khỏi PHP' \
      '    CGIPassAuth On' \
      '    RewriteEngine On' \
      '    RewriteCond %{REQUEST_FILENAME} !-f' \
      '    RewriteRule ^ index.php [L]' \
      '  </Directory>' \
      '  ErrorLog /proc/self/fd/2' \
      '  CustomLog /proc/self/fd/1 "%h %{X-Request-ID}i \"%r\" %>s %b %Dus"' \
      '</VirtualHost>' > /etc/apache2/sites-available/000-default.conf \
 && useradd --system --uid 10001 --home-dir /var/www/review app  && mkdir /data && chown app:app /data

WORKDIR /var/www/review
COPY openapi.json ./
COPY public/ public/
COPY src/ src/

# tiến trình Apache xử lý request chạy bằng uid 10001 (dùng chung với các service khác, xem deploy/backup)
ENV TDTU_ROOT=/var/www/review DATA_DIR=/data APACHE_RUN_USER=app APACHE_RUN_GROUP=app
VOLUME /data
EXPOSE 8005
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD php -r "exit(@file_get_contents('http://127.0.0.1:8005/health') === false ? 1 : 0);"
