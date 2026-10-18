# Restaurant Service (Node.js/Express + node:sqlite, cổng 8002). Build: docker build -t tdtu-food/restaurant services/restaurant
FROM node:24-alpine

ENV NODE_ENV=production
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY openapi.json ./
COPY src/ src/
# uid 10001 dùng chung cho mọi service có dữ liệu (container sao lưu cũng chạy bằng uid này)
RUN adduser -S -u 10001 app && mkdir /data && chown 10001:10001 /data
USER 10001

ENV TDTU_ROOT=/app DATA_DIR=/data BIND_HOST=0.0.0.0
VOLUME /data
EXPOSE 8002
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:8002/health').then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"
CMD ["node", "--disable-warning=ExperimentalWarning", "src/server.js"]
