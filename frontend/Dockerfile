FROM cgr.dev/chainguard/node:latest-dev AS build

USER root
RUN npm install -g npm@latest

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build
RUN npm prune --omit=dev

FROM cgr.dev/chainguard/node:latest

WORKDIR /app

COPY --from=build --chown=nonroot:nonroot /app/node_modules ./node_modules
COPY --from=build --chown=nonroot:nonroot /app/dist ./dist
COPY --from=build --chown=nonroot:nonroot /app/package.json ./
COPY --from=build --chown=nonroot:nonroot /app/astro.config.mjs ./

EXPOSE 4321

CMD ["node_modules/.bin/astro", "preview", "--host", "0.0.0.0"]
