# In production, point npm at the internal registry mirror (spec §8):
#   docker build --build-arg NPM_REGISTRY=https://npm.internal.example.local .
FROM node:22-alpine AS build
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /build
COPY package.json package-lock.json* ./
RUN npm config set registry ${NPM_REGISTRY} && npm install
COPY index.html vite.config.js ./
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html
EXPOSE 80
