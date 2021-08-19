FROM python:3-alpine
COPY operate.py /operate.py
RUN apk add py3-requests py3-requests-oauthlib
ENTRYPOINT ["python3"]
CMD ["/operate.py"]