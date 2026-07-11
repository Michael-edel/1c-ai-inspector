FROM node:22-alpine

RUN mkdir -p /app && chown node:node /app
USER node
WORKDIR /app
COPY --chown=node:node package.json package-lock.json tsconfig.json tsconfig.node.json vite.config.ts index.html /app/
RUN npm ci
COPY --chown=node:node src /app/src

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
