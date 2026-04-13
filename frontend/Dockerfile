FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .

# In production, backend is at the same host (nginx proxy)
ENV VITE_WS_URL=""

RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html

# Nginx config to proxy /api and /ws to backend
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
