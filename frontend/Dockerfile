# Builds the web app and serves it with nginx, which also proxies /api (and
# its WebSockets) to the backend so the browser talks to one origin.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Empty = same origin as the web app (the nginx proxy below).
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
# Where the API is reachable from this container.
ENV API_UPSTREAM=http://backend:8000
EXPOSE 80
