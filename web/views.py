# views.py
#
# Copyright (C) 2011-2022 Vas Vasiliadis
# University of Chicago
#
# Application logic for the GAS
#
##
__author__ = 'Vas Vasiliadis <vas@uchicago.edu>'

import uuid
import time
import json
from datetime import datetime
import time
import sys
import os

import boto3
from botocore.client import Config
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from flask import (abort, flash, redirect, render_template, 
  request, session, url_for)

from app import app, db
from decorators import authenticated, is_premium

import auth
# sys.path.insert(1, "/home/ubuntu/gas/util")
# import helpers

"""Start annotation request
Create the required AWS S3 policy document and render a form for
uploading an annotation input file using the policy document

Note: You are welcome to use this code instead of your own
but you can replace the code below with your own if you prefer.
"""

## MY CODE ##

# Global variables
region = app.config['AWS_REGION_NAME']


@app.route('/annotate', methods=['GET'])
@authenticated
def annotate():
    '''
    Route handler that creates a presigned post request
    and passes it into the template.
    '''

    unique_id = f"/{uuid.uuid4()}~"
    user_id = session['primary_identity']
    # Using ${}: https://stackoverflow.com/questions/965053/extract-filename-and-extension-in-bash
    key = f"{app.config['AWS_S3_KEY_PREFIX']}/" + user_id + unique_id + "${filename}"  
    
    # Define S3 policy fields and conditions
    acl = app.config['AWS_S3_ACL']
    bucket = app.config['AWS_S3_INPUTS_BUCKET']
    encryption = app.config['AWS_S3_ENCRYPTION']
    region = app.config["AWS_REGION_NAME"]
    
    # Generate signed POST request
    s3 = boto3.client('s3', config=Config(signature_version='s3v4'), region_name=region)
    
    # Generate presigned post: https://boto3.amazonaws.com/v1/documentation
    # /api/latest/reference/services/s3.html?highlight=presigned#S3.Client.generate_presigned_post
    # Understanding condition fields: https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-HTTPPOSTConstructPolicy.html
    try:
        response = s3.generate_presigned_post(
            Bucket=bucket,
            Key=key,
            Fields={"acl": acl, 
            "success_action_redirect": f"{request.base_url}/job",
            "x-amz-server-side-encryption": encryption},
            Conditions=[{"acl": acl}, 
            ["eq", "$success_action_redirect", f"{request.base_url}/job"],
            {"x-amz-server-side-encryption": encryption}],
            ExpiresIn=app.config['AWS_SIGNED_REQUEST_EXPIRATION'] 
        )
    
    # Used to debug redirect: https://stackoverflow.com/questions/47939068/accessdenied-invalid-according-to-policy-policy-condition-failed-starts-with
    # Other template/error support: https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3-presigned-urls.html
    except ClientError as e:
        app.logger.error(f'Unable to generate presigned URL for upload: {e}')
        return abort(500)

    # Render the upload form template
    return render_template("annotate.html", s3_post=response, role=session['role'])
"""Fires off an annotation job
Accepts the S3 redirect GET request, parses it to extract 
required info, saves a job item to the database, and then
publishes a notification for the annotator service.

Note: Update/replace the code below with your own from previous
homework assignments
"""
@app.route('/annotate/job', methods=['GET'])
@authenticated
def create_annotation_job_request():

    region = app.config['AWS_REGION_NAME']
    # Parse redirect URL query parameters for S3 object info
    bucket_name = request.args.get('bucket')
    key = request.args.get('key')
    user_id = session['primary_identity']

    # Extract job ID
    key_lst = key.split("~")
    input_file_name = key_lst[1]
    job_id = key_lst[0].split("/")[-1]
    
    # Time stamp: https://www.geeksforgeeks.org/get-current-timestamp-using-python/ 
    ts = int(time.time())
  
  # Create a job item and persist it to the annotations database
    db_data = { "job_id": job_id, 
              "user_id": user_id, 
              "input_file_name": input_file_name, 
              "s3_inputs_bucket": bucket_name, 
              "s3_key_input_file": key, 
              "submit_time": ts,
              "job_status": "PENDING"
            }
    
    # Create table resource: https://binaryguy.tech/aws/dynamodb/update-items-in-dynamodb-using-python/
    table_name = app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"]
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    
    # Dynamo DB documentation: https://boto3.amazonaws.com/v1
    # /documentation/api/latest/reference/services/dynamodb.html#DynamoDB.Client.put_item
    try:
        table.put_item(Item=db_data)
    except ClientError as e:
        app.logger.error(f'Unable to update database: {e}')
        return abort(500)
    
    # Create topic: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sns.html#SNS.Topic
    topic_arn = app.config["AWS_SNS_JOB_REQUEST_TOPIC"]
    sns = boto3.resource("sns", region_name=region)
    # helpers.publish_message_in_topic(topic_arn, sns, db_data)
    try:
        topic = sns.Topic(topic_arn)
    except ClientError as e:
        app.logger.error(f'Unable to connect to topic: {e}')
        return abort(500)
    
    # Publishing a message: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sns.html#SNS.Topic.publish
    try:
        resp = topic.publish(Message=json.dumps(db_data))
    except ClientError as e:
        app.logger.error(f'Unable to publish message: {e}')
        return abort(500)
        
    return render_template('annotate_confirm.html', job_id=job_id)


"""List all annotations for the user
"""
@app.route('/annotations', methods=['GET'])
@authenticated
def annotations_list():

    jobs = []
    region = app.config['AWS_REGION_NAME']
    table_name = app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"]
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    user_id = session['primary_identity']
    
    # First answer in post: https://stackoverflow.com/questions/35758924/
    # how-do-we-query-on-a-secondary-index-of-dynamodb-using-boto3
    try:
        response = table.query(IndexName="user_id_index", 
            KeyConditionExpression=Key("user_id").eq(user_id))
    except ClientError as e:
        app.logger.error(f'Unable to query database: {e}')
        return abort(500)
    for job in response["Items"]:
        job_item = {}
        job_item["job_id"] = job["job_id"]
        submit_time = int(job["submit_time"])

        # Used first answer on post: https://stackoverflow.com/questions/
        # 12400256/converting-epoch-time-into-the-datetime
        job_item["request_time"] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(submit_time))
        
        job_item["input_file_name"] = job["input_file_name"]
        job_item["status"] = job["job_status"]
        jobs.append(job_item)
  # Get list of annotations to display
  
    return render_template('annotations.html', jobs=jobs)


"""Display details of a specific annotation job
"""
@app.route('/annotations/<id>', methods=['GET'])
@authenticated
def annotation_details(id):


    job_details = {}
    region = app.config['AWS_REGION_NAME']
    table_name = app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"]
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    s3_client = boto3.client('s3', region_name=region)
    user_id = session['primary_identity']
    user_role = session["role"]

    # Check if this user is allowed to view this job
    try:
        auth_response = table.query(KeyConditionExpression=Key("job_id").eq(id))
    except ClientError as e:
        app.logger.error(f'Job ID not found: {e}')
        return abort(500)
    job_id_user_id = auth_response["Items"][0]["user_id"]
    if user_id != job_id_user_id:
        return abort(403)
    
    # Used query documentation: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb.html#DynamoDB.Table.query
    # Query DynamoDB using user_id and filter by job_id
    try:
        response = table.query(IndexName="user_id_index", 
            KeyConditionExpression=Key("user_id").eq(user_id), FilterExpression=Attr('job_id').eq(id))
    except ClientError as e:
        app.logger.error(f'The requested job ID does not exist for this authorized user: {e}')
        return abort(500)
    
    # Extract job detail parameters from DynamoDB response
    job_details["request_id"] = response["Items"][0]["job_id"]
    submit_time = int(response["Items"][0]["submit_time"])
    job_details["request_time"] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(submit_time))
    job_details["input_file_name"] = response["Items"][0]["input_file_name"]
    job_status = response["Items"][0]["job_status"]
    job_details["status"] = job_status
    input_file_key = response["Items"][0]['s3_key_input_file']
    input_bucket = app.config["AWS_S3_INPUTS_BUCKET"]
    
    # Generate presigned url to be able to download input file
    try:
        input_file_response = s3_client.generate_presigned_url('get_object', 
                    Params={'Bucket': input_bucket,
                    'Key': input_file_key}, 
                    ExpiresIn=app.config['AWS_SIGNED_REQUEST_EXPIRATION'])
                                                    
    except ClientError as e:
        app.logger.error(f'The results file could not be downloaded: {e}')
        return abort(500)
    
    # Modify html page with completed job details
    if job_status == "COMPLETED":
        # complete_time = response["Items"][0]["complete_time"]
        # job_details["complete_time"] = helpers.convert_time(complete_time)
        complete_time = int(response["Items"][0]["complete_time"])
        results_bucket = app.config['AWS_S3_RESULTS_BUCKET']
        object_name = response["Items"][0]["s3_key_result_file"]
        job_details["complete_time"] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(complete_time))
        job_details["user_role"] = session["role"]

        
        # Logic to check if 5 minutes have passed and if archive ID exists for a user
        try:
            archive_response = table.query(
                        KeyConditionExpression=Key('job_id').eq(job_details["request_id"])
                        )
        except ClientError as e:
            print(e)
        archive_attr = "results_file_archive_id"
        job_details["can_download_job"] = True
        
        if archive_attr in archive_response["Items"][0].keys():
            if user_role == "free_user":
                job_details["can_download_job"] = False
            
            # Check if file is being thawed for premium user
            else:
                restore_attr = "restore_job_id"
                if restore_attr in auth_response["Items"][0].keys():
                    restore_job_id = auth_response["Items"][0]["restore_job_id"]
                    glacier_client = boto3.client("glacier", region_name=region)
                    vault_name = app.config["AWS_GLACIER_VAULT"]

                    # Access glacier job details
                    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier.html#Glacier.Client.describe_job
                    try:
                        glacier_job_response = glacier_client.describe_job(vaultName=vault_name, jobId=restore_job_id)
                    except ClientError as e:
                        print(e)
                        if e.response["Error"]["Code"] == "ResourceNotFoundException":
                            return (f"A restoration job with the given ID does not exist: {e}")
                    
                    # Retrieve glacier job status code
                    thaw_status = glacier_job_response["StatusCode"]
                    if thaw_status == "InProgress":
                        job_details["can_download_job"] = False
                    elif thaw_status != "Succeeded":
                        job_details["can_download_job"] = False
                        return ("The restoration job failed.")
                else:
                    job_details["can_download_job"] = False

        if job_details["can_download_job"]:

            # https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3-presigned-urls.html
            try:
                s3_resp = s3_client.generate_presigned_url('get_object', 
                            Params={'Bucket': results_bucket,
                            'Key': object_name}, 
                            ExpiresIn=app.config['AWS_SIGNED_REQUEST_EXPIRATION'])
                                                        
            except ClientError as e:
                app.logger.error(f'The results file could not be downloaded: {e}')
                return abort(500)

            job_details["s3_resp"] = s3_resp

    return render_template('annotation.html', job_details=job_details, input_file_response=input_file_response)



"""Display the log file contents for an annotation job
"""
@app.route('/annotations/<id>/log', methods=['GET'])
@authenticated
def annotation_log(id):
  
    region = app.config['AWS_REGION_NAME']
    table_name = app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"]
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    user_id = session['primary_identity']

    # Check if this user is allowed to view this job
    try:
        auth_response = table.query(KeyConditionExpression=Key("job_id").eq(id))
    except ClientError as e:
        app.logger.error(f'Job ID not found: {e}')
        return abort(500)
    job_id_user_id = auth_response["Items"][0]["user_id"]
    if user_id != job_id_user_id:
        app.logger.error("The user does not have authorization to view this log file.")
        return abort(403)
    try:
        response = table.query(IndexName="user_id_index", 
            KeyConditionExpression=Key("user_id").eq(user_id), FilterExpression=Attr('job_id').eq(id))
    except ClientError as e:
        app.logger.error(f'The requested job ID does not belong to the authorized user: {e}')
        return abort(403)
    object_name = response["Items"][0]["s3_key_log_file"]
    bucket_name = app.config['AWS_S3_RESULTS_BUCKET']
    s3 = boto3.resource('s3')
    # First answer to post on reading s3 objects: https://stackoverflow.com/questions/31976273/open-s3-object-as-a-string-with-boto3
    try:
        log_file = s3.Object(bucket_name, object_name)
    except ClientError as e:
        print(e)
    try: 
        log_str = log_file.get()['Body'].read().decode('utf-8') 
    except ClientError as e:
        print(e)
    return render_template('view_log.html', log_str=log_str, id=id)

"""Subscription management handler
"""
import stripe
from auth import update_profile

@app.route('/subscribe', methods=['GET'])
@authenticated
def subscribe():

    if (request.method == 'GET'):
        
        # Display form to get subscriber credit card info
        return render_template('subscribe.html')

    elif (request.method == 'POST'):
        
        # Process the subscription request
        stripe_token = request.form["stripe_token"]
        stripe.api_key = app.config["STRIPE_SECRET_KEY"]
        username = session["name"]
        user_email = session["email"]
        price_id = app.config["STRIPE_PRICE_ID"]
        
        # Create a customer on Stripe
        # https://stripe.com/docs/api/errors/handling?lang=python
        # https://stripe.com/docs/api/customers/object?lang=python
        try:
            customer = stripe.Customer.create(name=username, email=user_email, card=stripe_token)
        except stripe.error.CardError as e:
          # Since it's a decline, stripe.error.CardError will be caught
            print(e)
            return jsonify({"status": e.http_status, "code": e.code, "message": e.user_message}, e.code)
        except stripe.error.InvalidRequestError as e:
          # Invalid parameters were supplied to Stripe's API
            print(e)
            return jsonify({"status": e.http_status, "code": e.code, "message": e.user_message}, e.code)
        except stripe.error.AuthenticationError as e:
          # Authentication with Stripe's API failed
          # (maybe you changed API keys recently)
            print(e)
            return jsonify({"status": e.http_status, "code": e.code, "message": e.user_message}, e.code)
        except stripe.error.StripeError as e:
            print(e)
            return jsonify({"status": e.http_status, "code": e.code, "message": e.user_message}, e.code)
        except Exception as e:
          # Something else happened, completely unrelated to Stripe
            print(e)
            return jsonify({"status": e.http_status, "code": e.code, "message": e.user_message}, e.code)
        
        # Subscribe customer to pricing plan
        customer_id = customer["id"]

        try:
            subscription = stripe.Subscription.create(customer=customer_id, items=[{"price": price_id}])
        except stripe.error.CardError as e:
          # Since it's a decline, stripe.error.CardError will be caught
            print(e)
            return jsonify({"status": e.http_status, "code": e.code, "message": e.user_message}, e.code)
        except stripe.error.InvalidRequestError as e:
          # Invalid parameters were supplied to Stripe's API
            print(e)
            return jsonify({"status": e.http_status, "code": e.code, "message": e.user_message}, e.code)
        except stripe.error.AuthenticationError as e:
          # Authentication with Stripe's API failed
          # (maybe you changed API keys recently)
            print(e)
            return jsonify({"status": e.http_status, "code": e.code, "message": e.user_message}, e.code)
        except stripe.error.StripeError as e:
            print(e)
            return jsonify({"status": e.http_status, "code": e.code, "message": e.user_message}, e.code)
        except Exception as e:
          # Something else happened, completely unrelated to Stripe
            print(e)
            return jsonify({"status": e.http_status, "code": e.code, "message": e.user_message}, e.code)
        
        # Update user role in accounts database
        user_id = session['primary_identity']
        try:
            auth.update_profile(identity_id=user_id, role="premium_user")
        except Exception as e:
            print(e)
            return jsonify({"status": "error", "code": 400, "message": 
                "Unable to update user's role to premium"}, 400)
        print("Updated user's role to premium in accounts database")
        
        # Update role in the session
        session["role"] = "premium_user"
        
        # Cancel pending archivals
        archive_queue = app.config["AWS_SQS_ARCHIVE_QUEUE_NAME"]
        wait_time = app.config["WAIT_TIME"]
        max_msgs = app.config["MAX_MSGS"]
        sqs = boto3.resource("sqs", region_name=region)
        try:
            queue = sqs.get_queue_by_name(QueueName=archive_queue)
        except ClientError as e:
            print(e)
            return jsonify({"status": "error", "code": 400, "message": "Unable to create queue with given name"}, 400)
        try:
            messages = queue.receive_messages(WaitTimeSeconds=wait_time, MaxNumberOfMessages=max_msgs)
        except ClientError as e:
            print(e)
            return jsonify({"status": "error", "code": 400, "message": "Unable to load messages from queue"}, 400)
        for message in messages:
            try:
                message.delete()
            except ClientError as e:
                print(e)
                return jsonify({"status": "error", "code": 400, "message": "Unable to delete message from queue"}, 400)
    

    # Initialize topic parameters
    topic_arn = app.config["AWS_SNS_THAW_TOPIC"]
    region = app.config['AWS_REGION_NAME']
    sns = boto3.resource("sns", region_name=region)
    archive_msg = {"user_id": user_id}
    # helpers.publish_message_in_topic(topic_arn, sns, archive_msg)
    # Publish message to topic with user_id
    try:
        topic = sns.Topic(topic_arn)
    except ClientError as e:
        app.logger.error(f'Unable to connect to topic: {e}')
        return abort(500)
    
    # Publishing a message: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sns.html#SNS.Topic.publish
    try:
        resp = topic.publish(Message=json.dumps(archive_msg))
    except ClientError as e:
        app.logger.error(f'Unable to publish message: {e}')
        return abort(500)
    print("Published message to thaw topic.")

    # Display confirmation page
    return render_template('subscribe_confirm.html', stripe_id=customer_id)




"""Set premium_user role
"""
@app.route('/make-me-premium', methods=['GET'])
@authenticated
def make_me_premium():
  # Hacky way to set the user's role to a premium user; simplifies testing
  update_profile(
    identity_id=session['primary_identity'],
    role="premium_user"
  )
  return redirect(url_for('profile'))


"""Reset subscription
"""
@app.route('/unsubscribe', methods=['GET'])
@authenticated
def unsubscribe():
  # Hacky way to reset the user's role to a free user; simplifies testing
  update_profile(
    identity_id=session['primary_identity'],
    role="free_user"
  )
  return redirect(url_for('profile'))


"""DO NOT CHANGE CODE BELOW THIS LINE
*******************************************************************************
"""

"""Home page
"""
@app.route('/', methods=['GET'])
def home():
  return render_template('home.html')

"""Login page; send user to Globus Auth
"""
@app.route('/login', methods=['GET'])
def login():
  app.logger.info(f"Login attempted from IP {request.remote_addr}")
  # If user requested a specific page, save it session for redirect after auth
  if (request.args.get('next')):
    session['next'] = request.args.get('next')
  return redirect(url_for('authcallback'))

"""404 error handler
"""
@app.errorhandler(404)
def page_not_found(e):
  return render_template('error.html', 
    title='Page not found', alert_level='warning',
    message="The page you tried to reach does not exist. \
      Please check the URL and try again."
    ), 404

"""403 error handler
"""
@app.errorhandler(403)
def forbidden(e):
  return render_template('error.html',
    title='Not authorized', alert_level='danger',
    message="You are not authorized to access this page. \
      If you think you deserve to be granted access, please contact the \
      supreme leader of the mutating genome revolutionary party."
    ), 403

"""405 error handler
"""
@app.errorhandler(405)
def not_allowed(e):
  return render_template('error.html',
    title='Not allowed', alert_level='warning',
    message="You attempted an operation that's not allowed; \
      get your act together, hacker!"
    ), 405

"""500 error handler
"""
@app.errorhandler(500)
def internal_error(error):
  return render_template('error.html',
    title='Server error', alert_level='danger',
    message="The server encountered an error and could \
      not process your request."
    ), 500

### EOF