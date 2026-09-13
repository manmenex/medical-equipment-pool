FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
# Probe 127.0.0.1, never `localhost`. This image's nginx.conf declares
# only `listen 80` (IPv4), and because that config differs from the
# packaged default, nginx's own 10-listen-on-ipv6-by-default.sh entrypoint
# deliberately skips adding `listen [::]:80`. The container's /etc/hosts
# maps `localhost` to BOTH 127.0.0.1 and ::1, and BusyBox wget resolves to
# ::1 first and does NOT fall back to IPv4 -- so `http://localhost/` was
# refused on every single probe while nginx was serving perfectly. Real
# Windows execution at baseline e3250091 measured a FailingStreak of 15.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
