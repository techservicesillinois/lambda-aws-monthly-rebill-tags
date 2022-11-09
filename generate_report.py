#!/usr/bin/env python3

import boto3
import datetime
import re

from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart

from botocore.exceptions import ClientError

#   event inputs required:
#   {
#       'tag-key': '[name of tag]',
#       'tag-value': '[value of tag]'
#       'days': 30   [number of days to go back, 30=1 month, 180=6 months, etc.]
#   }
def lambda_handler(event, context):
    # Create a Cost Explorer client
    client = boto3.client('ce')

    # Set time range to cover the last full calendar month
    # Note that the end date is EXCLUSIVE (e.g., not counted)
    now = datetime.datetime.utcnow()
    # Set the end of the range to start of the current month
    end = datetime.datetime(year=now.year, month=now.month, day=1)
    # Subtract 6 months and then "truncate" to the start of previous month
    start = end - datetime.timedelta(days=event['days'])
    start = datetime.datetime(year=start.year, month=start.month, day=1)
    # Get the month as string for email purposes
    month = start.strftime('%Y-%m')

    # Convert them to strings
    start = start.strftime('%Y-%m-%d')
    end = end.strftime('%Y-%m-%d')


    response = client.get_cost_and_usage(
        TimePeriod={
            'Start': start,
            'End':  end
        },
        Granularity='MONTHLY',
        Filter={
            'Tags': {
                'Key' : '{}'.format(event['tag-key']),
                'Values' : ['{}'.format(event['tag-value']),],
                'MatchOptions': ['EQUALS',]
            }
        },
        Metrics=['BlendedCost'],
        GroupBy=[
            {
                'Type': 'DIMENSION',
                'Key': 'SERVICE'
            },
        ]
    )

    #pprint.pprint()

    tsv_lines = []
    #append header row
    tsv_lines.append("Service\tStart Date\tAmount")
    
    for timeperiod in response["ResultsByTime"]:
        startdate = timeperiod["TimePeriod"]["Start"]
        for project in timeperiod["Groups"]:
            namestring = project['Keys'][0]

            amount = project['Metrics']['BlendedCost']['Amount']
            amount = float(amount)
            line = "{}\t{}\t${:,.2f}".format(namestring, startdate, amount)
            print(line)
            tsv_lines.append(line)


    send_email('{}'.format(event['tag-value']), 'from {} to {}'.format(start, end), "\n".join(tsv_lines))




def send_email(tag, report_dates, attachment):
    msg = MIMEMultipart()
    msg['From']  = "eepps2@illinois.edu"
    msg['To'] = "eepps2@illinois.edu"
    msg['Subject'] = "Monthly AWS Cost Breakdown: {}".format(tag)

    # what a recipient sees if they don't use an email reader
    msg.preamble = 'Multipart message.\n'

    # the message body
    part = MIMEText('Here is the AWS billing data {} for {}.'.format(report_dates, tag))
    msg.attach(part)

    # the attachment
    part = MIMEApplication(attachment)
    part.add_header('Content-Disposition', 'attachment', filename="AWS-MonthlyCostByTag-{}.tsv".format(tag))
    msg.attach(part)

    # Create an AWS Simple Email Service (SES) client
    client = boto3.client('ses')

    try:
        response = client.send_raw_email(
            RawMessage={
                 'Data': msg.as_string(),
            },
            #Source=msg['From'],
            #Destinations=to_emails
        )
    # Display an error if something goes wrong.
    except ClientError as e:
        print(e.response['Error']['Message'])
    else:
        print("Email sent! Message ID:"),
        print(response['ResponseMetadata']['RequestId'])



if __name__ == "__main__":
    lambda_handler({}, {})
