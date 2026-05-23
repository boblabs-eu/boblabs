# ---- Stage 1: Build React app ----
FROM node:18-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --legacy-peer-deps && npm install ajv@8 --legacy-peer-deps
COPY frontend/ .
ENV CI=false
RUN npm run build

# ---- Stage 2: Serve with nginx ----
FROM nginx:1.25-alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
# Copy documentation markdown files for the public docs page
COPY docs/ /usr/share/nginx/html/docs-md/
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
