FROM node:20-alpine AS deps
WORKDIR /app

COPY package.json /app/package.json
COPY tsconfig.base.json /app/tsconfig.base.json
COPY apps/web/package.json /app/apps/web/package.json
COPY packages/shared-types/package.json /app/packages/shared-types/package.json
COPY packages/ui/package.json /app/packages/ui/package.json
COPY packages/config/package.json /app/packages/config/package.json

RUN npm install

FROM deps AS build
ARG VITE_API_BASE_URL=http://127.0.0.1:8000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY apps/web /app/apps/web
COPY packages/shared-types /app/packages/shared-types
COPY packages/ui /app/packages/ui
COPY packages/config /app/packages/config

RUN npm run build --workspace @travelmind/web

FROM nginx:1.27-alpine AS runtime
COPY infra/nginx/web.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/web/dist /usr/share/nginx/html

EXPOSE 80
