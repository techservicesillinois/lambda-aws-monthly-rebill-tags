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

def lambda_handler(event, context):
    client = boto3.client('ce')
    clientSTS = boto3.client('sts')

    dt_now = datetime.datetime.utcnow()
    dt_end = datetime.datetime(year=dt_now.year, month=dt_now.month, day=1)
    dt_start = dt_end - datetime.timedelta(days=event['days'])
    dt_start = datetime.datetime(year=dt_start.year, month=dt_start.month, day=1)

    start = dt_start.strftime('%Y-%m-%d')
    end = dt_end.strftime('%Y-%m-%d')

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

    account_number = clientSTS.get_caller_identity()["Account"]

    arr_account_number = []
    arr_tag_value = []
    arr_service = []
    arr_month = []
    arr_amount = []
    for timeperiod in response_cost["ResultsByTime"]:
        month = timeperiod["TimePeriod"]["Start"].replace("-01","")
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

    num_rows = len(arr_amount) + 1

    xl_file_df = {'Account': arr_account_number, event['tag-key']: arr_tag_value, 'Service': arr_service, 'Month': arr_month, 'Amount': arr_amount}
    xl_file = pd.DataFrame(xl_file_df)

    xl_output = io.BytesIO()
    xl_writer = pd.ExcelWriter(xl_output)
    xl_file.to_excel(xl_writer, sheet_name='Sheet1')

    xl_wb = xl_writer.book
    xl_ws = xl_wb.active

    xl_ws.move_range("B1:F{}".format(num_rows), rows=0, cols=-1, translate=True)

    if event['show-chart'] == 1:
        from openpyxl.chart import BarChart, Reference, Series
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

    from openpyxl.worksheet.table import Table, TableStyleInfo
    xl_table = Table(displayName="AWS", ref="A1:E{}".format(num_rows))
    xl_table_style = TableStyleInfo(name="TableStyleMedium9", showFirstColumn=False, showLastColumn=False, showRowStripes=True, showColumnStripes=False)
    xl_table.tableStyleInfo = xl_table_style
    xl_ws.add_table(xl_table)

    xl_ws['E{}'.format(num_rows + 1)] = '=SUBTOTAL(9,AWS[Amount])'

    for row in range(1, num_rows + 2):
        xl_ws.cell(column=5, row=row).number_format = '#,##0.00'

    xl_writer.close()
    xl_file_att = xl_output.getvalue()

    send_email(tag_email_display, 'from {} to {}'.format(start, end), xl_file_att)


def send_email(tag, report_dates, attachment):
    msg = MIMEMultipart()
    msg['From'] = event['email-from']
    msg['To']  = event['email-to']
    msg['Subject'] = "AWS Cost Breakdown: {}".format(tag)

    msg.preamble = 'Multipart message.\n'

    part = MIMEText('Here is the AWS billing data {} for the Tag {}.'.format(report_dates, tag))
    msg.attach(part)

    part = MIMEApplication(attachment)
    part.add_header('Content-Disposition', 'attachment', filename="AWS-MonthlyCostByTag-{}.xlsx".format(tag))
    msg.attach(part)

    client = boto3.client('ses')

    try:
        response = client.send_raw_email(
            RawMessage={
                 'Data': msg.as_string(),
            }
        )
    except ClientError as e:
        print(e.response['Error']['Message'])
    else:
        print("Email sent! Message ID:"),
        print(response['ResponseMetadata']['RequestId'])



if __name__ == "__main__":
    lambda_handler({}, {})
