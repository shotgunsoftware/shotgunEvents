FROM python:2.7

RUN pip install git+git://github.com/shotgunsoftware/python-api.git

WORKDIR /app

COPY . /app

CMD [ "python","./src/shotgunEventDaemon.py", "foreground" ]