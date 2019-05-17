FROM python:3
WORKDIR /python

COPY . /python
RUN pip3 install -r requirements.txt

EXPOSE 8013
ENTRYPOINT [ "python3", "brother_ql_web.py" ]
