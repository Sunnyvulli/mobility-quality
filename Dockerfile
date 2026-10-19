FROM python:3.12-slim
WORKDIR /app
COPY pipeline.py api.py temporal.py test_system.py test_temporal.py ./
COPY data/hour.csv data/hour.csv
RUN python pipeline.py && python -m unittest -v
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=6 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()"
CMD ["python", "api.py", "--host", "0.0.0.0"]
