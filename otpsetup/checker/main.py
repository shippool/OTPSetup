#!/usr/bin/python

from boto import connect_s3
from boto.s3.key import Key
from kombu import Exchange, Queue
from otpsetup.shortcuts import DjangoBrokerConnection
from otpsetup.client.models import GtfsFile
from otpsetup import settings
from shutil import copyfileobj

import os
import subprocess
import tempfile

exchange = Exchange("amq.direct", type="direct", durable=True)
queue = Queue("validate_request", exchange=exchange, routing_key="validate_request")

def s3_bucket(cache = {}):
    if not 'bucket' in cache:
        
        connection = connect_s3(settings.AWS_ACCESS_KEY_ID, settings.AWS_SECRET_KEY)
        bucket = connection.get_bucket(settings.S3_BUCKET)
        cache['bucket'] = bucket
    else:
        return cache['bucket']
    return bucket


def validate(conn, body, message):
    #download the GTFS files and run them through the feed validator

    #create a working directory for this feed
    directory = tempfile.mkdtemp()

    files = body['files']
    out = []
    for s3_id in files:

        bucket = s3_bucket()
        key = Key(bucket)
        key.key = s3_id

        basename = os.path.basename(s3_id)
        path = os.path.join(directory, basename)
        
        key.get_contents_to_filename(path)
        result = subprocess.Popen(["feedvalidator.py", "-n", "--output=CONSOLE", "-l", "10", path], stdout=subprocess.PIPE)
        out.append({"key" : s3_id, "errors" : result.stdout.read()})
        os.remove(path)
    os.rmdir(directory)
    publisher = conn.Producer(routing_key="validation_done",
                              exchange=exchange)
    publisher.publish({'request_id' : body['request_id'], 'output' : out})
    message.ack()

with DjangoBrokerConnection() as conn:

    with conn.Consumer(queue, callbacks=[lambda body, message: validate(conn, body, message)]) as consumer:
        # Process messages and handle events on all channels
        while True:
            conn.drain_events()