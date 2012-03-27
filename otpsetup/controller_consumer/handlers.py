#!/usr/bin/python

from boto import connect_ec2
from kombu import Exchange
from django.core.mail import send_mail
from django.core.urlresolvers import reverse
from otpsetup.client.models import InstanceRequest, GtfsFile
from otpsetup import settings

exchange = Exchange("amq.direct", type="direct", durable=True)

def validation_done(conn, body):

    request_id = body['request_id']
    output = body['output']

    for gtfs_result in output:
        gtfs_file = GtfsFile.objects.get(s3_key=gtfs_result['key'])
        gtfs_file.validation_output = gtfs_result['errors']
        gtfs_file.save()

    irequest = InstanceRequest.objects.get(id=request_id)
    irequest.state = "submitted"
    irequest.save()

    #url = reverse("otpsetup.client.adminviews.index")

    send_mail('OTP instance request pending', 
              """There is a new OTP instance request which has just completed 
validation.  The request is from %s %s <%s>.  
""" % (irequest.user.first_name, irequest.user.last_name, 
       irequest.user.email),
              settings.DEFAULT_FROM_EMAIL,
              settings.ADMIN_EMAILS, fail_silently=False)


def graph_done(conn, body):

    request_id = body['request_id']
    success = body['success']

    if success:
        #publish a deploy_instance message
        publisher = conn.Producer(routing_key="deploy_instance", exchange=exchange)
        publisher.publish({'request_id' : request_id, 'key' : body['key'], 'output' : body['output']})

        #start a new deployment instance
        ec2_conn = connect_ec2(settings.AWS_ACCESS_KEY_ID, settings.AWS_SECRET_KEY) 

        image = ec2_conn.get_image(settings.DEPLOYMENT_AMI_ID) 

        print 'Launching EC2 Instance'
        reservation = image.run(subnet_id=settings.VPC_SUBNET_ID, placement='us-east-1b', key_name='otp-dev', instance_type='m1.large')

        for instance in reservation.instances:
            instance.add_tag("Name", "deploy-req-%s" % request_id)

    else:
        send_mail('OTP graph builder failed', 
            """An OTP instance request failed during the graph-building stage.
              
Request ID: %s

Graph Builder output:
%s  
""" % (request_id, body['output']),
            settings.DEFAULT_FROM_EMAIL,
            settings.ADMIN_EMAILS, fail_silently=False)