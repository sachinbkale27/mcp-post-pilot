# Builds both React apps and serves them with nginx, which also proxies their APIs.
# Build context: repository root.
FROM node:22-alpine AS build
WORKDIR /src
COPY blog-app/frontend/package.json blog-app/frontend/package-lock.json blog/
COPY agent-chat/frontend/package.json agent-chat/frontend/package-lock.json chat/
RUN cd blog && npm ci && cd ../chat && npm ci
COPY blog-app/frontend/ blog/
COPY agent-chat/frontend/ chat/
# Same-origin API calls; nginx routes /api/ to the right backend.
ENV VITE_API_URL=/api
RUN cd blog && npm run build && cd ../chat && npm run build

FROM nginx:1.27-alpine
COPY deploy/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/blog/dist /usr/share/nginx/blog
COPY --from=build /src/chat/dist /usr/share/nginx/chat
