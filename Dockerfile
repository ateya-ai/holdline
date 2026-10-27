FROM python:3.14.7-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOLD_LINE_LOAD_DOTENV=false
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt \
    && useradd --create-home --uid 10001 holdline
COPY --chown=holdline:holdline holdline holdline
COPY --chown=holdline:holdline app app
COPY --chown=holdline:holdline specialists specialists
COPY --chown=holdline:holdline mcp_tools mcp_tools
COPY --chown=holdline:holdline data data
COPY --chown=holdline:holdline skills skills
COPY --chown=holdline:holdline certs certs
RUN mkdir /app/.run && chown holdline:holdline /app/.run
USER holdline
EXPOSE 8741
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 CMD ["python", "-m", "holdline.healthcheck", "api"]
CMD ["python", "-m", "uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8741", "--no-access-log"]
