# Overview

Based on https://github.com/agussman/aws-cost-explorer

A simple Python 3 script to run via AWS Lambda to report monthly billing from AWS Cost Explorer split by Tag.

# Python source code

The Python source code is written in Python 3.8 and is included as a file in the Ansible role (/roles/create_lambda/files/generate_report.py). As part of the setup process, the .py file is pulled from a .zip archive in a publicly accessible S3 bucket for easy import into Lambda.

# Input values

Inputs required (JSON will be included in trigger and passed to the function in the event variable):
```
{
    'tag-key': '[name of tag]',       | the name of the tag to use for billing
    'tag-value': '[value of tag]'     | pass blank value to retrieve all tags
    'tag-value-default': '[default]'  | default value if desired for all untagged resources
    'days': 30                        | number of days to go back, 30=1 month, 180=6 months, etc.
    'show-chart': 1                   | add this if you want the chart to be displayed. no chart unless this is set to 1
    'email-from': '[email sent from]' | must be confirmed in AWS SES https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html#verify-email-addresses-procedure
    'email-to': '[email sent to]'     | must be confirmed in AWS SES https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html#verify-email-addresses-procedure
}
```

# Setup

Ansible install in lambda.yml via AWX. 

*Note: ability to add Pandas layer in Ansible/CLI is not available. For now, add the AWSSDKPandas-Python38 layer directly in the AWS console.*

# References

* [AWS Cost Explorer API](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-explorer-api.html)
* [Boto 3 Docs on CostExplorer](http://boto3.readthedocs.io/en/latest/reference/services/ce.html)
* [Amazon SES Quick Start](https://docs.aws.amazon.com/ses/latest/DeveloperGuide/quick-start.html)
* [Boto 3 Docs on SES](http://boto3.readthedocs.io/en/latest/reference/services/ses.html)
* [Sample code creating attachments](https://gist.github.com/yosemitebandit/2883593)
* [AWS Schedule Expressions for Rules](https://docs.aws.amazon.com/AmazonCloudWatch/latest/events/ScheduledEvents.html)
