# archive_app_config.py
#
# Copyright (C) 2011-2022 Vas Vasiliadis
# University of Chicago
#
# Set app configuration options for archive utility
#
##
__author__ = 'Vas Vasiliadis <vas@uchicago.edu>'

class Config(object):

  CSRF_ENABLED = True

  # AWS Settings
  AWS_REGION_NAME = "us-east-1"
  WAIT_TIME = 20
  MAX_MSGS = 10

  # AWS DynamoDB table
  AWS_DYNAMODB_ANNOTATIONS_TABLE = "dramaswamy_annotations"

    # AWS SNS topics
  AWS_ARCHIVE_TOPIC = "arn:aws:sns:us-east-1:127134666975:dramaswamy_a17_archive"

  # AWS SQS queues
  AWS_ARCHIVE_QUEUE = "dramaswamy_a17_archive"

  # LOCAL PATH
  LOCAL_PATH = "/home/ubuntu/gas/ann"

  # RESULTS BUCKET
  AWS_RESULTS_BUCKET = "gas-results"

  # GLACIER VAULT
  AWS_GLACIER_VAULT = "ucmpcs"

  # USER DB
  USER_DB = "dramaswamy_accounts"

### EOF