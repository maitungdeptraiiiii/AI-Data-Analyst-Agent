FROM python:3.12-slim
RUN useradd --create-home --uid 10001 sandbox
WORKDIR /sandbox
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY runner.py .
USER sandbox
ENTRYPOINT ["python", "/sandbox/runner.py"]
