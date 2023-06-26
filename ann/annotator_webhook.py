# annotator_webhook.py
#
# NOTE: This file lives on the AnnTools instance
# Modified to run as a web server that can be called by SNS to process jobs
# Run using: python annotator_webhook.py
#
# Copyright (C) 2011-2022 Vas Vasiliadis
# University of Chicago
##
__author__ = 'Vas Vasiliadis <vas@uchicago.edu>'

import requests
from flask import Flask, jsonify, request
import boto3
import json
from botocore.exceptions import ClientError
import subprocess
import os

app = Flask(__name__)
environment = 'ann_config.Config'
app.config.from_object(environment)



'''
A13 - Replace polling with webhook in annotator

Receives request from SNS; queries job queue and processes message.
Reads request messages from SQS and runs AnnTools as a subprocess.
Updates the annotations database with the status of the request.
'''
@app.route('/process-job-request', methods=['GET', 'POST'])
def annotate():

    
    if (request.method == 'GET'):
        return jsonify({
          "code": 405, 
          "error": "Expecting SNS POST request."
        }), 405

    # Check message type
    region = app.config["AWS_REGION_NAME"]
    topic_arn = app.config["AWS_REQUESTS_TOPIC"]
    sns_client = boto3.client('sns', region_name=region)
    
    # Confirm Subscription Request
    if request.headers["X-Amz-Sns-Message-Type"] == "SubscriptionConfirmation":
        # Parse data: https://stackoverflow.com/questions/63364498/get-data-from-json-by-python-flask
        message = json.loads(request.get_data())

    # Get request to extract token
        token = message["Token"]

        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sns.html#SNS.Client.confirm_subscription
        confirm_subscription = sns_client.confirm_subscription(TopicArn=topic_arn, Token=token)

    queue_name = app.config["AWS_REQUESTS_QUEUE"]
    wait_time = int(app.config["AWS_SQS_WAIT_TIME"])
    max_msgs = int(app.config["AWS_SQS_MAX_MESSAGES"])

    # Processing messages example: https://boto3.amazonaws.com/v1/documentation/api/latest/guide/sqs.html
    sqs = boto3.resource('sqs', region_name =region)
    try:
        queue = sqs.get_queue_by_name(QueueName=queue_name)
    except ClientError as e:
        print(e)
    else:
        try:
            messages = queue.receive_messages(WaitTimeSeconds=wait_time, MaxNumberOfMessages=max_msgs)
        except ClientError as e:
            print(e)
        else:
            if len(messages) == 0:
                print("ClientError: There are no messages in this queue.")
            else:
                for message in messages:
                    msg_body = json.loads(json.loads(message.body)["Message"])

                    # Extract job parameters from message
                    job_id = msg_body["job_id"]
                    input_file_name = msg_body["input_file_name"]
                    bucket_name = msg_body["s3_inputs_bucket"]
                    key = msg_body["s3_key_input_file"]
                    user_id = msg_body["user_id"]
                    path = app.config["ANNOTATOR_BASE_DIR"]
                    local_path = f"{path}/{job_id}~{input_file_name}"
                    
                    # Get the input file S3 object and copy it to a local file
                    s3 = boto3.resource('s3', region_name=region)
                    try:
                        s3.Bucket(bucket_name).download_file(key, local_path)
                    except ClientError as e:
                        print(e)
                    else:
                        # Launch annotation job as a background process
                        try:
                            job = subprocess.Popen(["python", f"{path}/run.py", 
                                local_path, path, user_id, job_id, input_file_name]) 
                        except ClientError as e:
                            print(e)
                        else:
                            table_name = app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"]
                            table = boto3.resource("dynamodb", region_name=region).Table(table_name)
                            try:
                                table.update_item(Key={"job_id": job_id},
                                            UpdateExpression= "set job_status = :r",
                                            ConditionExpression="job_status = :js",
                                            ExpressionAttributeValues={
                                            ":r": "RUNNING",
                                            ":js": "PENDING"}) 
                            except ClientError as e:
                                print(e)
                            else:
                            # Delete the message from the queue, if job was successfully submitted
                                try:
                                    message.delete()
                                except ClientError as e:
                                    print(e)
             

    return jsonify({
    "code": 200, 
    "message": "Annotation job request processed."
    }), 200

app.run('0.0.0.0', debug=True)

### EOF