FROM node:22-alpine

WORKDIR /app
COPY package.json tsconfig.json tsconfig.node.json vite.config.ts index.html /app/
RUN npm install
COPY src /app/src

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
