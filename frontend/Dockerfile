FROM node:22.14.0-alpine3.21 AS build

WORKDIR /app
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH

RUN corepack enable \
    && corepack prepare pnpm@9.15.4 --activate

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . ./
ARG VITE_API_BASE_URL=
ARG VITE_HTTP_TIMEOUT_MS=120000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_HTTP_TIMEOUT_MS=${VITE_HTTP_TIMEOUT_MS}
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.27.4-alpine AS runtime

COPY --chown=101:101 deploy/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build --chown=101:101 /app/dist/ /usr/share/nginx/html/

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
