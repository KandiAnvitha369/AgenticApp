# ==============================================================================
# Multi-Stage Optimized Dockerfile for SSC CGL RAG Chatbot (Frontend)
#
# Stage 1 (builder): Compiles React + Vite app with Node.js
# Stage 2 (runner) : Ultralight (~15MB) Nginx server for high-performance delivery
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build & Bundle Static Assets
# ------------------------------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

# Optimize npm install with clean cache handling
COPY package.json package-lock.json ./
RUN npm ci --prefer-offline --no-audit --no-fund

# Build-time API configuration (injected via Docker build arg)
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=${VITE_API_URL}

# Copy application source code
COPY . .

# Build production bundle and purge npm cache
RUN npm run build && \
    rm -rf /root/.npm


# ------------------------------------------------------------------------------
# Stage 2: Minimal Runtime Nginx Web Server
# ------------------------------------------------------------------------------
FROM nginx:alpine-slim AS runner

WORKDIR /usr/share/nginx/html

# Remove default Nginx welcome assets
RUN rm -rf ./*

# Copy built static assets from builder stage
COPY --from=builder /app/dist ./

# Copy optimized Nginx configuration (gzip, security headers, SPA routing)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# Built-in lightweight health check using Alpine's native BusyBox wget
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:80/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
