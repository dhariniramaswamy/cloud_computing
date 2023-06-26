# restore.py
#
# Restores thawed data, saving objects to S3 results bucket
# NOTE: This code is for an AWS Lambda function
#
# Copyright (C) 2011-2021 Vas Vasiliadis
# University of Chicago
##


import json
import boto3
from botocore.exceptions import ClientError

DYNAMODB_TABLE = "dramaswamy_annotations"
VAULT_NAME = "ucmpcs"
region = "us-east-1"
results_bucket = "gas-results"

def lambda_handler(event, context):
    
    message = json.loads(event['Records'][0]['Sns']['Message'])
    results_key = message["JobDescription"]
    glacier_job_id = message["JobId"]
    glacier = boto3.client("glacier", region_name=region)
    s3 = boto3.client("s3", region_name=region)
    print("Successfully extracted parameters from event")
    
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier/client/get_job_output.html
    try:
        response = glacier.get_job_output(vaultName=VAULT_NAME,
        jobId=glacier_job_id)
    except ClientError as e:
        print(e)
    print("Successfully retrieved glacier job output")
    body = response['body'].read()

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_object.html
    try:
        s3_resp = s3.put_object(Body=body, Bucket=results_bucket, Key=results_key)
    except ClientError as e:
        print(e)
    
    return {
        'statusCode': 200,
        'body': json.dumps('Successfully put results file in gas-results bucket')
    }