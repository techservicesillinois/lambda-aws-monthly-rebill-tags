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
#       'tag-value': '[value of tag]' | pass blank value to retrieve all tags
#       'days': 30 | number of days to go back, 30=1 month, 180=6 months, etc.
#   }
def lambda_handler(event, context):
    # Create a Cost Explorer client
    client = boto3.client('ce')

    # Set time range to cover the last full calendar month
    # Note that the end date is EXCLUSIVE (e.g., not counted)
    now = datetime.datetime.utcnow()
    # Set the end of the range to start of the current month
    end = datetime.datetime(year=now.year, month=now.month, day=1)
    # Subtract number of days and then "truncate" to the start of that month
    start = end - datetime.timedelta(days=event['days'])
    start = datetime.datetime(year=start.year, month=start.month, day=1)
    # Get the month as string for email purposes
    month = start.strftime('%Y-%m')

    # Convert them to strings
    start = start.strftime('%Y-%m-%d')
    end = end.strftime('%Y-%m-%d')

    # Get list of available tags
    tagValue = []
    if event['tag-value'] == '':
        responseTags = client.get_tags(
            TimePeriod={
                'Start': start,
                'End':  end
            },
            TagKey='{}'.format(event['tag-key'])
        )
        for tagVal in responseTags["Tags"]:
            tagValue.append(tagVal)
    else:
        tagValue.append('{}'.format(event['tag-value']))

    response = client.get_cost_and_usage(
        TimePeriod={
            'Start': start,
            'End':  end
        },
        Granularity='MONTHLY',
        Filter={
            'Tags': {
                'Key' : '{}'.format(event['tag-key']),
                'Values' : tagValue,
                'MatchOptions': ['EQUALS',]
            }
        },
        Metrics=['BlendedCost'],
        GroupBy=[
            {
                'Type': 'TAG',
                'Key': '{}'.format(event['tag-key'])
            },
            {
                'Type': 'DIMENSION',
                'Key': 'SERVICE'
            },
        ]
    )

    #pprint.pprint()

    tsv_lines = []
    #append header row
    tsv_lines.append("{}\tService\tMonth\tAmount".format(event['tag-key']))
    
    for timeperiod in response["ResultsByTime"]:
        startdate = timeperiod["TimePeriod"]["Start"].replace("-01","")
        for groups in timeperiod["Groups"]:
            service = groups['Keys'][1]
            tag_value = groups['Keys'][0].replace('{}$'.format(event['tag-key']),'')
            if tag_value == '':
                tag_value = '[no tag]'

            amount = groups['Metrics']['BlendedCost']['Amount']
            amount = float(amount)
            line = "{}\t{}\t{}\t${:,.2f}".format(tag_value, service, startdate, amount)
            print(line)
            tsv_lines.append(line)


    send_email('{}'.format(event['tag-value']), 'from {} to {}'.format(start, end), "\n".join(tsv_lines))




def send_email(tag, report_dates, attachment):
    msg = MIMEMultipart()
    msg['From']  = "eepps2@illinois.edu"
    msg['To'] = "eepps2@illinois.edu"
    msg['Subject'] = "AWS Cost Breakdown: {}".format(tag)

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
