# Genomics Annotation Service
This web application used distributed system design principles in AWS that allows users to upload genome sequences for annotation. Utilized a RESTful Web API in Flask and Python, publish-subscribe pattern with SQS and SNS, Stripe for payment processing, S3 and Glacier storage, DynamoDB, serverless computing (Lambda).

Adds robust user authentication (via [Globus Auth](https://docs.globus.org/api/auth)), modular templates, and some simple styling based on [Bootstrap](https://getbootstrap.com/docs/3.3/).

Directory contents are as follows:
* `/web` - The GAS web app files
* `/ann` - Annotator files
* `/util` - Utility scripts/apps for notifications, archival, and restoration
* `/aws` - AWS user data files

Credit for course materials goes to Vas Vasiliadis - University of Chicago MPCS Professor.
	

