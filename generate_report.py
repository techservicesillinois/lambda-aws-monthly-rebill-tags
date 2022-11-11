#!/usr/bin/env python3

import boto3
import datetime
import re

import pandas as pd
import openpyxl
import io

from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart

from botocore.exceptions import ClientError

#   event inputs required:
#   {
#       'tag-key': '[name of tag]',
#       'tag-value': '[value of tag]' | pass blank value to retrieve all tags
#       'tag-value-default': '[default]' | default value if desired for all untagged resources
#       'days': 30 | number of days to go back, 30=1 month, 180=6 months, etc.
#       'show-chart': 1 | add this if you want the chart to be displayed. no chart unless this is set to 1
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

    # If there is no tag value specified, get a list of available tag
    #  values for the provided key
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

    # get the usage data, filtered by tag and grouped by tag/service
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
    
    # process retrieved response data into arrays ready to pandas DataTable
    arr_tag_value = []
    arr_service = []
    arr_month = []
    arr_amount = []
    for timeperiod in response["ResultsByTime"]:
        month = timeperiod["TimePeriod"]["Start"].replace("-01","")
        for groups in timeperiod["Groups"]:
            service = groups['Keys'][1]
            tag_value = groups['Keys'][0].replace('{}$'.format(event['tag-key']),'')
            if tag_value == '':
                if event['tag-value-default'] == '':
                    tag_value = '[no tag]'
                else:
                    tag_value = event['tag-value-default']

            amount = groups['Metrics']['BlendedCost']['Amount']
            amount = float(amount)
            arr_tag_value.append(tag_value)
            arr_service.append(service)
            arr_month.append(month) 
            arr_amount.append(amount)

    # Get the number of rows (plus 1) for use in formatting Excel file
    num_rows = len(arr_amount) + 1
    
    # create pandas DataFrame from output values
    xl_file_df = {event['tag-key']: arr_tag_value, 'Service': arr_service, 'Month': arr_month, 'Amount': arr_amount}
    xl_file = pd.DataFrame(xl_file_df)

    # write Excel output to a stream
    output = io.BytesIO()
    writer = pd.ExcelWriter(output)
    xl_file.to_excel(writer, sheet_name='Sheet1')

    # Get active book/sheet for further processing
    wb = writer.book
    ws = wb.active
    
    # get rid of useless first column
    ws.move_range("B1:E{}".format(num_rows), rows=0, cols=-1, translate=True)
    
    if event['show-chart'] == 1:
        # Generate chart based on data table
        from openpyxl.chart import BarChart, Reference, Series
        # create chart in Excel file
        xl_chart = BarChart()
        xl_chart.type = "col"
        xl_chart.style = 10
        xl_chart.title = "AWS Charges by Month"
        xl_chart.y_axis.title = 'AWS Charges'
        xl_chart.x_axis.title = 'Month'
        data = Reference(ws, min_col=3, min_row=1, max_row=num_rows, max_col=4)
        cats = Reference(ws, min_col=3, min_row=2, max_row=num_rows, max_col=3)
        xl_chart.add_data(data, titles_from_data=True)
        xl_chart.set_categories(cats)
        xl_chart.shape = 4
        xl_chart.legend.overlay = 0
        ws.add_chart(xl_chart, "G2")

    # add table with default styling (striped rows and banded columns)
    from openpyxl.worksheet.table import Table, TableStyleInfo
    xl_table = Table(displayName="AWS", ref="A1:D{}".format(num_rows))
    style = TableStyleInfo(name="TableStyleMedium9", showFirstColumn=False,
                           showLastColumn=False, showRowStripes=True, showColumnStripes=True)
    xl_table.tableStyleInfo = style
    ws.add_table(xl_table)

    # save/close file
    writer.close()
    # get file content from stream
    xl_file_att = output.getvalue()

    # send email with Excel file attachment data
    send_email('{}'.format(event['tag-value']), 'from {} to {}'.format(start, end), xl_file_att)


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
    part.add_header('Content-Disposition', 'attachment', filename="AWS-MonthlyCostByTag-{}.xlsx".format(tag))
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
