# Two stages so the host needs no Node: the build happens here, and what ships
# is static files behind Caddy.
FROM node:22-alpine AS build
WORKDIR /build

# Dependencies first, so this layer is cached when only source changes.
COPY web/package.json web/package-lock.json ./
RUN npm ci

# The API contract lives outside web/ because the native client imports it too,
# so the build context is the repository root and shared/ has to come along.
COPY shared/ ../shared/
COPY web/ ./
RUN npm run build

FROM caddy:2-alpine
# Caddy rather than nginx: the stack already speaks Caddy, and one server to
# understand is worth more than a marginally smaller image.
COPY --from=build /build/dist /srv
COPY web/Caddyfile /etc/caddy/Caddyfile
EXPOSE 8080
