FROM python:3.11-slim

WORKDIR /app

# Create unprivileged sandbox user and group to prevent root container breakouts
RUN groupadd -g 1000 sandboxgroup && \
    useradd -u 1000 -g sandboxgroup -m -s /bin/bash sandboxuser

RUN pip install --no-cache-dir fastapi uvicorn pydantic requests

COPY main.py /app/main.py

# Drop root privileges for runtime execution
USER sandboxuser

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
