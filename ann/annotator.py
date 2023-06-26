'''
MPCS 51083
A10: GAS Framework Migration
Dharini Ramaswamy
'''


import subprocess
import os
import boto3
from botocore.exceptions import ClientError
import json

# Get configuration
from configparser import ConfigParser
config = ConfigParser()
config.read('ann_config.ini')

# Connect to SQS and get the message queue
region= config.get("aws", "AwsRegionName")
queue_name = config.get("sqs", "queue")
wait_time = int(config.get("aws", "wait_time"))
max_msgs = int(config.get("aws", "max_msgs"))

# Processing messages example: https://boto3.amazonaws.com/v1/documentation/api/latest/guide/sqs.html
sqs = boto3.resource('sqs', region_name =region)
try:
    queue = sqs.get_queue_by_name(QueueName=queue_name)
except ClientError as e:
    print(e)
else:
    # Poll the message queue in a loop 
    while True:
        # Attempt to read a message from the queue
        try:
            messages = queue.receive_messages(WaitTimeSeconds=wait_time, MaxNumberOfMessages=max_msgs)
        except ClientError as e:
            print(e)
        else:
            if len(messages) > 0:
                print(f"Receiving {len(messages)} messages.")
                
                for message in messages:
                    msg_body = json.loads(json.loads(message.body)["Message"])

                    # Extract job parameters from message
                    job_id = msg_body["job_id"]
                    input_file_name = msg_body["input_file_name"]
                    bucket_name = msg_body["s3_inputs_bucket"]
                    key = msg_body["s3_key_input_file"]
                    user_id = msg_body["user_id"]
                    path = config.get("ann", "path")
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
                            table_name = config.get("dynamodb", "db")
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
             