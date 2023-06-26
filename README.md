# GAS Framework
An enhanced web framework (based on [Flask](https://flask.palletsprojects.com/)) for use in the capstone project. Adds robust user authentication (via [Globus Auth](https://docs.globus.org/api/auth)), modular templates, and some simple styling based on [Bootstrap](https://getbootstrap.com/docs/3.3/).

Directory contents are as follows:
* `/web` - The GAS web app files
* `/ann` - Annotator files
* `/util` - Utility scripts/apps for notifications, archival, and restoration
* `/aws` - AWS user data files

A16 Write-Up
Specifics of Approach:
For this assignment, I used queues, topics, and a Lambda function to ensure data persistence, consistency, and scalability. Once the 
annotation, archival, and subscription upgrade process are complete, I begin the thaw process. In the `/subscribe` endpoint in `views.py`, I published a message containing the user ID to the "dramaswamy_a16_thaw" topic, which then sent the message to the thaw queue. I created a webhook `thaw_app.py` so that the thawing process would only begin when there were messages in the thaw queue. Once the message is published to the thaw topic, the `/thaw` endpoint is triggered. At this stage, I extract the user ID from the message in the thaw queue and use it to query DynamoDB for job details. I check to see if the file has been archived; if it has not been, I skip to the next message in the queue because we do not want to restore files that have not been archived. If a file has been archived, I initiate a Glacier job (expedited request) to restore the file. If the expedited request fails, then I catch the error and initiate a standard request job. Once this goes through, I upload the restoration job ID that comes from job initiation response output to DynamoDB so that the restoration process is associated with the correct request job ID (Note: the restoration job ID and the request job ID are different). Then, I delete the message from the thaw queue. The message is only deleted from the queue once the restoration process is initiated; the queue allows us to persist the job data. I created another topic "dramaswamy_a16_restore" that I use in my Lambda function. This topic is subscribed to Glacier, so that whenever Glacier finishes restoring a file, it publishes a message to the topic. Once the topic receives the message, the Lambda function is triggered. To make sure that the results files had the correct prefixes/location in the `gas-results` bucket, I queried the results file prefix from DynamoDB in `thaw_app.py` using the user_id. I then passed this prefix into the "Description parameter" of the Glacier initate job method. In the Lambda function, I extracted the 
results file prefix from the message that was published by Glacier. Since the restored file from Glacier is in a bytes StreamingBody() format, I read it and then put the object in the `gas-results` bucket using the correct results file prefix.
	

