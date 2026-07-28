FROM node:20-alpine

WORKDIR /app

# Nejdřív jen package.json, ať se cachuje npm install
COPY package*.json ./
RUN npm install --force

COPY . .

EXPOSE 3000

# --host 0.0.0.0 je klíčové - jinak vite poslouchá jen na localhost
# uvnitř kontejneru a zvenku se na to nikdy nedostaneš
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
