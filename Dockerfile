FROM python:3.7.17-alpine
ENV SG_CONF_DIR=""
COPY requirements.txt src/ shotgunEvents/
WORKDIR shotgunEvents

RUN pip install -r requirements.txt

VOLUME ["/shotgunEvents/plugins"]

ENTRYPOINT ["python", "shotgunEventDaemon.py", "start"]

CMD []