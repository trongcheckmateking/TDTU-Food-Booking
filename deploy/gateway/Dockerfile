# Gateway (Nginx): HTTPS, một tên miền cho cả hệ thống, định tuyến /svc/<service>/, chặn /internal, giới hạn tần suất.
# Build: docker build -t tdtu-food/gateway deploy/gateway
FROM nginx:1.28-alpine

RUN apk add --no-cache openssl && mkdir -p /var/www/acme /etc/nginx/certs
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY 05-tdtu.envsh /docker-entrypoint.d/05-tdtu.envsh
RUN sed -i 's/\r$//' /docker-entrypoint.d/05-tdtu.envsh /etc/nginx/templates/default.conf.template \
 && chmod 755 /docker-entrypoint.d/05-tdtu.envsh

# 15-local-resolvers.envsh của image đặt NGINX_LOCAL_RESOLVERS (DNS nội bộ của Docker) cho lệnh resolver
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 SERVER_NAME=localhost HTTPS_PORT=443
EXPOSE 80 443
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -qO /dev/null http://127.0.0.1/healthz || exit 1
