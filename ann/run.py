# run.py
#
# Copyright (C) 2011-2019 Vas Vasiliadis
# University of Chicago
#
# Wrapper script for running AnnTools
#
##
__author__ = 'Vas Vasiliadis <vas@uchicago.edu>'

import sys
import time
import driver
import boto3
from botocore.exceptions import ClientError
import os
import time


# Get configuration
from configparser import ConfigParser
config = ConfigParser()
config.read('ann_config.ini')

# Import helpers.py
# https://blog.finxter.com/python-how-to-import-modules-from-another-folder/
helpers_path = config.get("util", "helpers_path")
sys.path.append(helpers_path)
import helpers
#from helpers import get_user_profile


"""A rudimentary timer for coarse-grained profiling
"""
class Timer(object):
  def __init__(self, verbose=True):
    self.verbose = verbose

  def __enter__(self):
    self.start = time.time()
    return self

  def __exit__(self, *args):
    self.end = time.time()
    self.secs = self.end - self.start
    if self.verbose:
      print(f"Approximate runtime: {self.secs:.2f} seconds")

if __name__ == '__main__':
    # Call the AnnTools pipeline
    if len(sys.argv) > 1:
        with Timer():
            driver.run(sys.argv[1], 'vcf')
            
            # extract args from config and sys.arg
            local_path = sys.argv[1]
            root_path = sys.argv[2]
            job_id = sys.argv[4]
            user_id = sys.argv[3]
            input_file_full_name = sys.argv[5]
            input_file_name = input_file_full_name.split(".")[0]
            local_results_file = f"{root_path}/{job_id}~{input_file_name}.annot.vcf"
            local_log_file = f"{local_path}.count.log"
            results_bucket = config.get("s3", "bucket_results")
            cnetid = config.get("prefix", "cnetid")

            # create results and log keys
            key_results = cnetid + user_id + f"/{job_id}~{input_file_name}" + ".annot.vcf"
            key_log = cnetid + user_id + f"/{job_id}~{input_file_full_name}" + ".count.log"

            # connect to s3 and upload results/log files
            s3_client = boto3.client('s3')
            # Boto3 documentation: https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3-uploading-files.html
            try:
                response_results = s3_client.upload_file(local_results_file, results_bucket, key_results)
                response_log = s3_client.upload_file(local_log_file, results_bucket, key_log)
            except ClientError as e:
                print(e)

            # connect to dynamodb and update job item
            region = config.get("aws", "AwsRegionName")
            table_name = config.get("dynamodb", "db")
            table = boto3.resource("dynamodb", region_name=region).Table(table_name)
            complete_time = int(time.time())
            
            # Updating DB: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GettingStarted.UpdateItem.html
            try:
                table.update_item(Key={"job_id": job_id},
                    UpdateExpression= "set job_status = :r, s3_results_bucket = :b,\
                    s3_key_result_file = :kr, s3_key_log_file = :kl, complete_time = :cl",
                    ExpressionAttributeValues={
                    ":r": "COMPLETED", ":b": results_bucket, ":kr": key_results, 
                    ":kl": key_log,":cl": complete_time})    
            except ClientError as e:
                print(e)
            
            ### NEW CODE FOR A14 ###

            topic_arn = config["sns"]["archive_topic"]
            duration = config.get("aws", "duration")
           
            # Create archive message to pass into step function
            # First answer that formats input: https://stackoverflow.com/questions/55379944/pass-variable-into-step-function-start-execution-input-parameter
            archive_message = "{\"job_id\": \"" + job_id + "\", \"topic_arn\": \"" + topic_arn + "\", \"duration\": \
            \"" + duration + "\", \"user_id\": \"" + user_id + "\"}"
            
            # Initialize step function client and start execution
            # Step Function documentation: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/stepfunctions.html#SFN.Client.start_execution
            step_function_client = boto3.client('stepfunctions', region_name=region)
            machine_arn = config.get("step_function", "state_machine_arn")
            try:
                machine_resp = step_function_client.start_execution(
                                stateMachineArn=machine_arn,
                                name=job_id,
                                input= archive_message
                                )
            except ClientError as e:
                print(e)
            print("Success: Starting state machine execution")

            # Delete local copies of files
            os.remove(local_results_file)
            os.remove(local_log_file)
            os.remove(local_path)
else:
   print("A valid .vcf file must be provided as input to this program.")

### EOF