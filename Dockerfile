FROM python:3
COPY operate.py /operate.py
RUN apt-get update
RUN apt-get install -y python3-requests python3-paramiko python3-requests-oauthlib
ENTRYPOINT ["python3.7"]
CMD ["/operate.py"]