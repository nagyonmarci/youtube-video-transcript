FROM node:22-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build
RUN chown -R node:node /app

USER node

EXPOSE 4321

CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0"]
