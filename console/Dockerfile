# Build context is the repository root, so nginx.conf can be copied from infra/.
FROM node:22-alpine AS build
WORKDIR /src
COPY console/package.json console/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY console/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /src/dist /usr/share/nginx/html
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
