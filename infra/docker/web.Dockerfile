FROM library/node:24.15.0-bookworm-slim@sha256:4e6b70dd6cbfc88c8157ba19aa3d9f9cce6ba4703576d55459e45efcbc9c5f5d AS development
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.33.0 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web apps/web
RUN pnpm install --frozen-lockfile
RUN chown -R node:node /app
USER node
EXPOSE 5173
CMD ["pnpm", "--filter", "@floatchat/web", "dev"]
FROM development AS build
RUN pnpm --filter @floatchat/web build
