# Frontend container — a real two-stage build, unlike the backend:
# `npm run build` produces static HTML/JS/CSS files, and none of the
# Node toolchain that produced them needs to exist in the final image.
# Stage 1 does the build; stage 2 is just nginx serving the output —
# the final image never contains Node, npm, or node_modules at all.

FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# VITE_API_BASE_URL must be supplied at BUILD time, not run time — Vite
# inlines import.meta.env.VITE_* into the compiled JS during `npm run
# build`, so this has to be a build-arg here, passed through docker-
# compose.yml as VITE_API_BASE_URL. Changing it after the image is
# built means rebuilding, not just restarting the container — a real,
# easy-to-miss gotcha with any Vite app in Docker, worth stating
# plainly rather than leaving someone to discover it the hard way.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
