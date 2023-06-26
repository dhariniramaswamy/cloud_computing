# thaw_app.py
#
# Thaws upgraded (premium) user data
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

from flask import Flask, request, jsonify

app = Flask(__name__)
environment = 'thaw_app_config.Config'
app.config.from_object(environment)
app.url_map.strict_slashes = False

@app.route('/', methods=['GET'])
def home():
    return (f"This is the Thaw utility: POST requests to /thaw.")

@app.route('/thaw', methods=['POST'])
def thaw_premium_user_data():


    # Confirm subscription between archive topic and this endpoint
    # HTTP/HTTPS notification JSON format: https://docs.aws.amazon.com/sns/latest/dg/sns-message-and-json-formats.html
    region = app.config["AWS_REGION_NAME"]
    topic_arn = app.config["AWS_SNS_THAW"]
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
    
    queue_name = app.config["AWS_SQS_THAW_QUEUE"]
    sqs = boto3.resource('sqs', region_name =region)
    wait_time = app.config["WAIT_TIME"]
    max_msgs = app.config["MAX_MSGS"]

    table_name = app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"]
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    glacier = boto3.client('glacier', region_name=region)
    vault_name = app.config["AWS_GLACIER_VAULT_NAME"]
    results_bucket = app.config["AWS_RESULTS_BUCKET"]
    glacier_topic = app.config["AWS_SNS_RESTORE"]
    restore_job_params = {"Type": "archive-retrieval", "SNSTopic": glacier_topic, "Tier": "Expedited"}
    
    try:
        queue = sqs.get_queue_by_name(QueueName=queue_name)
    except ClientError as e:
        print(e)
        return jsonify({"code": 404, "status": "error", 
            "message": "Unable to find a queue with the given name"}, 404)
    else:
        try:
            messages = queue.receive_messages(WaitTimeSeconds=wait_time, MaxNumberOfMessages=max_msgs)
        except ClientError as e:
            print(e)
            return jsonify({"code": 400, "status": "error", 
                "message": "Unable to load messages from the queue"}, 400)
        else:
            if len(messages) > 0:
                print(f"Receiving {len(messages)} messages.")
                
                for message in messages:
                    msg_body = json.loads(json.loads(message.body)["Message"])
                    user_id = msg_body["user_id"]
    
                    # Get all job items for a given user
                    try:
                        db_resp = table.query(IndexName="user_id_index", 
                        KeyConditionExpression=Key("user_id").eq(user_id))
                    except ClientError as e:
                        print(e)
                        return jsonify({"code": 400, "status": "error", 
                            "message": "Unable to query database with given user_id"}, 400)

                    # Update restore job parameters with results file key and archive ID
                    archive_attr = "results_file_archive_id"
                    for job_item in db_resp["Items"]:
                        restore_job_params["Tier"] = "Expedited"
                        
                        # If file hasn't been archived, move onto next job
                        if archive_attr not in job_item.keys():
                            continue
                        
                        # Add archive id and results file key to params dict
                        archive_id = job_item[archive_attr]
                        prefix = job_item["s3_key_result_file"]
                        requests_job_id = job_item["job_id"]
                        restore_job_params["ArchiveId"] = archive_id
                        # restore_job_params["OutputLocation"]["S3"]["Prefix"] = prefix
                        restore_job_params["Description"] = prefix
                        print("Extracted parameters from DynamoDB response")

                        # Initiate archive retrieval with expedited tier
                        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier.html#Glacier.Client.initiate_job
                        try:
                            archive_response = glacier.initiate_job(vaultName=vault_name, 
                                jobParameters = restore_job_params)
                        except ClientError as e:
                            # if e.response["Error"]["Code"] == "ServiceUnavailableException":
                            #     print("Expedited retrieval request failed. Attempting standard retrieval.")
                            
                            # If expedited tier fails, try again with standard tier
                            print(e)
                            print("Expedited retrieval request failed. Beginning standard retrieval request.")
                            restore_job_params["Tier"] = "Standard"
                            try:
                                archive_response = glacier.initiate_job(vaultName=vault_name, 
                            jobParameters = restore_job_params)
                            except ClientError as e:
                                print(e)
                                return jsonify({"code": 400, "status": "error", 
                                    "message": "Unable to initiate glacier job for standard retrieval request"}, 400)
                            print("Standard retrieval request succeeded.")

                        # Update dynamoDB with glacier job ID
                        restore_job_id = archive_response['jobId']
                        try:
                            table.update_item(Key={"job_id": requests_job_id},
                                            UpdateExpression= "set restore_job_id = :r",
                                            ExpressionAttributeValues={":r": restore_job_id}
                                            )
                        except ClientError as e:
                            print(e)
                            return jsonify({"code": 400, "status": "error", 
                                "message": "Unable to update DynamoDB with restore job id"}, 400)
                        print("Updated DynamoDB with restoration job id.")

                    # Delete message from thaw queue
                    try:
                        message.delete()
                    except ClientError as e:
                        print(e)
                        return jsonify({"code": 400, "status": "error", 
                            "message": "Unable to delete message from thaw queue."}, 400)
                    print("Deleted message from thaw queue")
    
    return jsonify({"status": "restoration process complete", "code": 200}, 200)
                   
        

# Run using dev server (remove if running via uWSGI)
app.run('0.0.0.0', debug=True, port=5001)
### EOF
