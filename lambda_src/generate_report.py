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
#       'tag-value': '[value of tag]'     | pass blank value to retrieve all tags
#       'tag-value-default': '[default]'  | default value if desired for all untagged resources
#       'days': 30                        | number of days to go back, 30=1 month, 180=6 months, etc.
#       'show-chart': 1                   | add this if you want the chart to be displayed. no chart unless this is set to 1
#       'email-from': '[email sent from]' | must be confirmed in AWS SES https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html#verify-email-addresses-procedure
#       'email-to': '[email sent to]'     | must be confirmed in AWS SES https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html#verify-email-addresses-procedure
#   }
def lambda_handler(event, context):
    # Create a Cost Explorer client
    client = boto3.client('ce')
    clientSTS = boto3.client('sts')

    # Set time range to cover the last full calendar month
    # Note that the end date is EXCLUSIVE (e.g., not counted)
    dt_now = datetime.datetime.utcnow()
    # Set the end of the range to start of the current month
    dt_end = datetime.datetime(year=dt_now.year, month=dt_now.month, day=1)
    # Subtract number of days and then "truncate" to the start of that month
    dt_start = dt_end - datetime.timedelta(days=int(event['days']))
    dt_start = datetime.datetime(year=dt_start.year, month=dt_start.month, day=1)

    # Convert them to strings
    start = dt_start.strftime('%Y-%m-%d')
    end = dt_end.strftime('%Y-%m-%d')

    # If there is no tag value specified, get a list of available tag
    #  values for the provided key
    arr_input_tag_value = []
    if event['tag-value'] == '':
        response_tags = client.get_tags(
            TimePeriod={
                'Start': start,
                'End':  end
            },
            TagKey='{}'.format(event['tag-key'])
        )
        for input_tag_value in response_tags["Tags"]:
            arr_input_tag_value.append(input_tag_value)
        tag_email_display = 'All {}'.format(event['tag-key'])
    else:
        arr_input_tag_value.append('{}'.format(event['tag-value']))
        tag_email_display = event['tag-value']

    # get the usage data, filtered by tag and grouped by tag/service
    response_cost = client.get_cost_and_usage(
        TimePeriod={
            'Start': start,
            'End':  end
        },
        Granularity='MONTHLY',
        Filter={
            'Tags': {
                'Key' : '{}'.format(event['tag-key']),
                'Values' : arr_input_tag_value,
                'MatchOptions': ['EQUALS',]
            }
        },
        Metrics=['UnblendedCost'],
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
    
    # get account number
    account_number = clientSTS.get_caller_identity()["Account"]
    
    # process retrieved response data into arrays ready to pandas DataTable
    arr_account_number = []
    arr_tag_value = []
    arr_service = []
    arr_month = []
    arr_amount = []
    for timeperiod in response_cost["ResultsByTime"]:
        month = timeperiod["TimePeriod"]["Start"]
        month = month[:7]
        for groups in timeperiod["Groups"]:
            service = groups['Keys'][1]
            tag_value = groups['Keys'][0].replace('{}$'.format(event['tag-key']),'')
            if tag_value == '':
                if event['tag-value-default'] == '':
                    tag_value = '[no tag]'
                else:
                    tag_value = event['tag-value-default']

            amount = groups['Metrics']['UnblendedCost']['Amount']
            amount = float(amount)
            arr_account_number.append(account_number)
            arr_tag_value.append(tag_value)
            arr_service.append(service)
            arr_month.append(month) 
            arr_amount.append(amount)

    # Get the number of rows (plus 1) for use in formatting Excel file
    num_rows = len(arr_amount) + 1
    
    # create pandas DataFrame from output values
    xl_file_df = {'Account': arr_account_number, 'Tag': arr_tag_value, 'Service': arr_service, 'Month': arr_month, 'Amount': arr_amount}
    xl_file = pd.DataFrame(xl_file_df)

    # write Excel output to a stream
    xl_output = io.BytesIO()
    xl_writer = pd.ExcelWriter(xl_output)
    xl_file.to_excel(xl_writer, sheet_name='Sheet1')

    # Get active book/sheet for further processing
    xl_wb = xl_writer.book
    xl_ws = xl_wb.active
    
    # get rid of first column
    xl_ws.move_range("B1:F{}".format(num_rows), rows=0, cols=-1, translate=True)
    
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
        data = Reference(xl_ws, min_col=4, min_row=2, max_row=num_rows, max_col=5)
        cats = Reference(xl_ws, min_col=4, min_row=3, max_row=num_rows, max_col=4)
        xl_chart.add_data(data, titles_from_data=True)
        xl_chart.set_categories(cats)
        xl_chart.shape = 4
        ws.add_chart(xl_chart, "H2")

    # add table with default styling (striped rows)
    from openpyxl.worksheet.table import Table, TableStyleInfo
    xl_table = Table(displayName="AWS", ref="A1:E{}".format(num_rows))
    xl_table_style = TableStyleInfo(name="TableStyleMedium9", showFirstColumn=False, showLastColumn=False, showRowStripes=True, showColumnStripes=False)
    xl_table.tableStyleInfo = xl_table_style
    xl_ws.add_table(xl_table)
    
    # add subtotal to table
    xl_ws['E{}'.format(num_rows + 1)] = '=SUBTOTAL(9,AWS[Amount])'
        
    # format amount column to 2 decimal points, dollar sign on subtotal
    for row in range(1, num_rows + 2):
        xl_ws.cell(column=5, row=row).number_format = '#,##0.00'

    # save/close file
    xl_writer.close()
    # get file content from stream
    xl_file_att = xl_output.getvalue()
    
    # send email with Excel file attachment data
    send_email(event, tag_email_display, 'from {} to {}'.format(start, end), xl_file_att)


def send_email(event, tag, report_dates, attachment):
    msg = MIMEMultipart()
    msg['From'] = event['email-from']
    msg['To']  = event['email-to']
    msg['Subject'] = "AWS Cost Breakdown: {}".format(tag)

    # what a recipient sees if they don't use an email reader
    msg.preamble = 'Multipart message.\n'

    # the message body
    part = MIMEText('Here is the AWS billing data {} for the Tag {}.'.format(report_dates, tag))
    msg.attach(part)

    # the attachment
    part = MIMEApplication(attachment)
    part.add_header('Content-Disposition', 'attachment', filename="AWS-MonthlyCostByTag-{}.xlsx".format(tag).replace(' ','_'))
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
