FROM node:22-alpine

WORKDIR /app

RUN apk add --no-cache python3 py3-pip
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies first for better layer caching.
COPY package*.json ./
COPY requirements-data.txt ./
RUN npm ci
RUN pip install --no-cache-dir -r requirements-data.txt

COPY . .

EXPOSE 3000

# Bind to all interfaces so the dev server is reachable from outside the container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
