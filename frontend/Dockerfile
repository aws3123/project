# ── Stage 1: Build ──
FROM node:22-alpine AS builder
WORKDIR /app

# Install pnpm via corepack
RUN corepack enable
RUN pnpm config set dangerouslyAllowAllBuilds true

# Install dependencies (leverage Docker cache)
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy source and build
COPY . .
ARG VITE_API_BASE_URL=
ARG VITE_API_KEY=
ARG VITE_API_KEY_HEADER=X-API-Key
ARG VITE_HTTP_TIMEOUT_MS=15000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_API_KEY=${VITE_API_KEY} \
    VITE_API_KEY_HEADER=${VITE_API_KEY_HEADER} \
    VITE_HTTP_TIMEOUT_MS=${VITE_HTTP_TIMEOUT_MS}
RUN pnpm build

# ── Stage 2: Serve with Nginx ──
FROM nginx:1.27-alpine
# Remove default nginx config
RUN rm -f /etc/nginx/conf.d/default.conf
# Copy nginx template (envsubst at runtime)
COPY deploy/nginx/default.conf.template /etc/nginx/templates/default.conf.template
# Copy built assets
COPY --from=builder /app/dist/ /usr/share/nginx/html/
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
