FROM python:3.12-slim

ARG CELLPOSE_LOCAL_MODELS_PATH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CELLPOSE_LOCAL_MODELS_PATH=${CELLPOSE_LOCAL_MODELS_PATH}

RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --create-home app \
    && mkdir -p /app "${CELLPOSE_LOCAL_MODELS_PATH}" \
    && chown -R app:app /app "${CELLPOSE_LOCAL_MODELS_PATH}"

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY --chown=app:app app.py ./app.py
COPY --chown=app:app healthcheck.py ./healthcheck.py
COPY --chown=app:app cellpose_config.py ./cellpose_config.py
USER app

CMD ["sh", "-c", "exec python -m uvicorn app:app --host \"$CELLPOSE_CONTAINER_HOST\" --port \"$CELLPOSE_CONTAINER_PORT\" --workers \"$CELLPOSE_WORKERS\""]
