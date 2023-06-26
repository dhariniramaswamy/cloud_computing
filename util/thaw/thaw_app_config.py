# thaw_app_config.py
#
# Copyright (C) 2011-2021 Vas Vasiliadis
# University of Chicago
#
# Set app configuration options for thaw utility
#
##
__author__ = 'Vas Vasiliadis <vas@uchicago.edu>'

import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config(object):

  CSRF_ENABLED = True

  
  # AWS Settings
  AWS_REGION_NAME = "us-east-1"
  WAIT_TIME = 20
  MAX_MSGS = 10

  # AWS DynamoDB table
  AWS_DYNAMODB_ANNOTATIONS_TABLE = "dramaswamy_annotations"

  # AWS SNS Queues
  AWS_SQS_THAW_QUEUE = "dramaswamy_a17_thaw"

  # AWS SNS Topics
  AWS_SNS_RESTORE = "arn:aws:sns:us-east-1:127134666975:dramaswamy_a17_restore"
  AWS_SNS_THAW = "arn:aws:sns:us-east-1:127134666975:dramaswamy_a17_thaw"

  # AWS S3 Glacier Vault Name
  AWS_GLACIER_VAULT_NAME = "ucmpcs"

  # AWS S3 Buckets
  AWS_RESULTS_BUCKET = "gas-results"

### EOF
