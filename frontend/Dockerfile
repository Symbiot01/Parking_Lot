# Build
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_URL=http://localhost:8010
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# Runtime — static files via `serve` (no nginx)
FROM node:22-alpine

WORKDIR /app

RUN npm install -g serve@14

COPY --from=build /app/dist ./dist

EXPOSE 8011

CMD ["serve", "-s", "dist", "-l", "8011"]
