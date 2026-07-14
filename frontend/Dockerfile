FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json tsconfig.json tsconfig.node.json vite.config.ts index.html /app/
RUN npm ci
COPY src /app/src
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

USER 101
EXPOSE 5173
HEALTHCHECK --interval=10s --timeout=3s --retries=10 CMD wget -q -O /dev/null http://127.0.0.1:5173/ || exit 1
