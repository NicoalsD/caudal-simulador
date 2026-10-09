# Image of the simulator dashboard and API (caudal-sim tablero).
# Stage 1 builds the dashboard; stage 2 installs the locked Python environment and runs it
# as a non-root user. No key, password or .env file is copied into the image.

# syntax=docker/dockerfile:1

ARG NODE_IMAGE=docker.io/library/node:24-alpine
ARG PYTHON_IMAGE=docker.io/library/python:3.12-slim
ARG UV_VERSION=0.12.15
ARG APP_USER=caudal
ARG APP_UID=10001

FROM ${NODE_IMAGE} AS dashboard-build
WORKDIR /dashboard
RUN corepack enable
COPY dashboard/package.json dashboard/pnpm-lock.yaml dashboard/.npmrc ./
RUN pnpm install --frozen-lockfile
COPY dashboard/ ./
RUN pnpm build

FROM ${PYTHON_IMAGE} AS runtime
ARG UV_VERSION
ARG APP_USER
ARG APP_UID
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:${PATH}" \
    CAUDAL_SIM_DASHBOARD_HOST=0.0.0.0 \
    CAUDAL_SIM_DASHBOARD_PORT=8000
RUN pip install --no-cache-dir "uv==${UV_VERSION}" \
 && groupadd --system --gid ${APP_UID} ${APP_USER} \
 && useradd --system --uid ${APP_UID} --gid ${APP_USER} --no-create-home --shell /usr/sbin/nologin ${APP_USER}
WORKDIR /app
# Dependencies first, so that a code change does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY scenarios ./scenarios
RUN uv sync --locked --no-dev
COPY --from=dashboard-build /dashboard/dist ./dashboard/dist
RUN chown -R root:root /app && chmod -R a+rX /app
USER ${APP_USER}
EXPOSE 8000
# Publish the port on loopback only: docker run -p 127.0.0.1:8000:8000 ...
ENTRYPOINT ["caudal-sim"]
CMD ["tablero"]
