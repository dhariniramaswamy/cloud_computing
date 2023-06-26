# archive_app.py
#
# Archive free user data
#
# Copyright (C) 2011-2021 Vas Vasiliadis
# University of Chicago
##
__author__ = 'Vas Vasiliadis <vas@uchicago.edu>'

import json
import os
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
import requests
import sys
sys.path.insert(1, os.path.realpath(os.path.pardir))
import helpers

from flask import Flask, request,jsonify, abort

app = Flask(__name__)
environment = 'archive_app_config.Config'
app.config.from_object(environment)


@app.route('/', methods=['GET'])
def home():
    return (f"This is the Archive utility: POST requests to /archive.")

@app.route('/archive', methods=['POST'])
def archive_free_user_data():
    '''
    Archives annotations results file to S3 Glacier.
    '''

    # Confirm subscription between archive topic and this endpoint
    # HTTP/HTTPS notification JSON format: https://docs.aws.amazon.com/sns/latest/dg/sns-message-and-json-formats.html
    region = app.config["AWS_REGION_NAME"]
    topic_arn = app.config["AWS_ARCHIVE_TOPIC"]
    sns_client = boto3.client('sns', region_name=region)
    
    if request.headers["X-Amz-Sns-Message-Type"] == "SubscriptionConfirmation":
        # Parse data: https://stackoverflow.com/questions/63364498/get-data-from-json-by-python-flask
        message = json.loads(request.get_data())
        token = message["Token"]

        # Confirm subscription example: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sns.html
        try:
            confirm_subscription = sns_client.confirm_subscription(TopicArn=topic_arn, Token=token)
        except ClientError as e:
            print(e)
            return jsonify({"code": 400, "status": "error", 
                "message": "Unable to confirm subscription."}, 400)
        print("Subscription has been confirmed")


    # Process queue messages
    sqs = boto3.resource('sqs', region_name =region)
    wait_time = app.config["WAIT_TIME"]
    max_msgs = app.config["MAX_MSGS"]
    queue_name = app.config["AWS_ARCHIVE_QUEUE"]
    db = app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"]
    user_db = app.config["USER_DB"]
    try:
        queue = sqs.get_queue_by_name(QueueName=queue_name)
    except:
        print(e)
        return jsonify({"code": 404, "status": "error", 
            "message": "Unable to access queue with given name"}, 404)
    else:
        try:
            messages = queue.receive_messages(WaitTimeSeconds=wait_time, MaxNumberOfMessages=max_msgs)
        except ClientError as e:
            print(e)
            return jsonify({"code": 400, "status": "error", 
                "message": "Unable to load messages for given queue."}, 400)
        else:
            if len(messages) > 0:
                print(f"Received {len(messages)} messages.")
            
            # Parse message body and extract job parameters
            for message in messages:
                msg_body = json.loads(json.loads(message.body)["Message"])
                job_id = msg_body["job_id"]
                user_id = msg_body["user_id"]
                user_profile = helpers.get_user_profile(id=user_id, db_name=user_db)
                user_role = user_profile[4]
                if user_role == "premium_user":
                    try:
                        message.delete()
                    except ClientError as e:
                        print(e)
                        return jsonify({"code": 400, "status": "error", 
                            "message": "Unable to delete message from archive queue."}, 400)
                    return jsonify({"status": f"User role is {user_role}. Stopped archival process.", \
                        "code": 200}, 200)
                table = boto3.resource("dynamodb", region_name=region).Table(db)
                try:
                    db_response = table.query(KeyConditionExpression=Key('job_id').eq(job_id))
                except ClientError as e:
                    print(e)
                    return jsonify({"code": 400, "status": "error", 
                        "message": "Unable to query database with given job ID"}, 400)
                results_key = db_response["Items"][0]["s3_key_result_file"]
                
                # Initialize S3 bucket and S3 Glacier
                s3 = boto3.resource('s3', region_name=region)
                bucket_name = app.config["AWS_RESULTS_BUCKET"]
                bucket = s3.Bucket(bucket_name)
                glacier_client = boto3.client('glacier', region_name=region)
                vault_name = app.config["AWS_GLACIER_VAULT"]
                
                # Access the results file object
                # Used second answer: https://stackoverflow.com/questions/41833565/s3-buckets-to-glacier-on-demand-is-it-possible-from-boto3-api
                try:
                    results_file_object = bucket.objects.filter(Prefix=results_key)
                except ClientError as e:
                    print(e)
                    return jsonify({"code": 400, "status": "error", 
                        "message": "Unable to filter S3 bucket with given prefix"}, 400)
                
                # Upload results file body to S3 Glacier and update DynamoDB with archive ID
                for obj_summary in results_file_object:
                    try:
                        glacier_response = glacier_client.upload_archive(vaultName=vault_name,\
                            body=obj_summary.get()['Body'].read())
                    except ClientError as e:
                        print(e)
                        return jsonify({"code": 400, "status": "error", 
                            "message": "Unable to upload archive to S3 Glacier."}, 400)
                    archive_id = glacier_response["archiveId"]
                    print(f"Retrieved glacier archive_id: {archive_id}")
                    try:
                        table.update_item(Key={"job_id": job_id},
                                            UpdateExpression= "set results_file_archive_id = :r",
                                            ExpressionAttributeValues={":r": archive_id}
                                            )
                    except ClientError as e:
                        print(e)
                        return jsonify({"code": 400, "status": "error", 
                            "message": "Unable to update DynamoDB with archive ID."}, 400)
                    print("Updated DynamoDB with glacier archive id")
                
                # Delete results file from S3 bucket
                # Delete objects documentation: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html?highlight=delete#S3.Client.delete_object
                try:
                    delete_file = bucket.delete_objects(Delete={
                        'Objects':[{
                        'Key': results_key
                        }]
                        })
                except ClientError as e:
                    print(e)
                    return jsonify({"code": 400, "status": "error", 
                        "message": "Unable to delete results file from S3 Bucket"}, 400)
                print("Deleted results file from gas-results")
                
                # Delete message from archive queue
                try:
                    message.delete()
                except ClientError as e:
                    print(e)
                    return jsonify({"code": 400, "status": "error", 
                        "message": "Unable to delete message from archive queue."}, 400)
                print("Deleted message from archive queue")
                
    return jsonify({"status": "archive process complete", "code": 200}, 200)

# Run using dev server (remove if running via uWSGI)
app.run('0.0.0.0', debug=True)
### EOF