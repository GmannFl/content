import base64
import json
import os
import re
import traceback
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import demistomock as demisto  # noqa: F401
import requests
from CommonServerPython import *  # noqa: F401
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

register_module_line('Microsoft Graph Mail Single User', 'start', __line__())


''' IMPORTS '''


# Disable insecure warnings
requests.packages.urllib3.disable_warnings()

''' GLOBAL VARS '''

DATE_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

# Well known folders shortcut in MS Graph API
# For more information: https://docs.microsoft.com/en-us/graph/api/resources/mailfolder?view=graph-rest-1.0
WELL_KNOWN_FOLDERS = {
    'archive': 'archive',
    'conversation history': 'conversationhistory',
    'deleted items': 'deleteditems',
    'drafts': 'drafts',
    'inbox': 'inbox',
    'junk email': 'junkemail',
    'outbox': 'outbox',
    'sent items': 'sentitems',
}

EMAIL_DATA_MAPPING = {
    'id': 'ID',
    'createdDateTime': 'CreatedTime',
    'lastModifiedDateTime': 'ModifiedTime',
    'receivedDateTime': 'ReceivedTime',
    'sentDateTime': 'SentTime',
    'subject': 'Subject',
    'importance': 'Importance',
    'conversationId': 'ConversationID',
    'isRead': 'IsRead',
    'isDraft': 'IsDraft',
    'internetMessageId': 'MessageID'
}

''' HELPER FUNCTIONS '''


def add_second_to_str_date(date_string, seconds=1):
    """
    Add seconds to date string.

    Is used as workaround to Graph API bug, for more information go to:
    https://stackoverflow.com/questions/35729273/office-365-graph-api-greater-than-filter-on-received-date

    :type date_string: ``str``
    :param date_string: Date string to add seconds

    :type seconds: int
    :param seconds: Seconds to add to date, by default is set to 1

    :return: Date time string appended seconds
    :rtype: ``str``
    """
    added_result = datetime.strptime(date_string, DATE_FORMAT) + timedelta(seconds=seconds)
    return datetime.strftime(added_result, DATE_FORMAT)


def upload_file(filename, content, attachments_list):
    """
    Uploads file to War room.

    :type filename: ``str``
    :param filename: file name to upload

    :type content: ``str``
    :param content: Content of file to upload

    :type attachments_list: ``list``
    :param attachments_list: List of uploaded file data to War Room
    """
    file_result = fileResult(filename, content)

    if is_error(file_result):
        demisto.error(file_result['Contents'])
        raise Exception(file_result['Contents'])

    attachments_list.append({
        'path': file_result['FileID'],
        'name': file_result['File']
    })


def read_file_and_encode64(attach_id):
    """
    Reads file that was uploaded to War Room and encodes it's content to base 64.

    :type attach_id: ``str``
    :param attach_id: The id of uploaded file to War Room

    :return: Base 64 encoded data, size of the encoded data in bytes and uploaded file name.
    :rtype: ``bytes``, ``int``, ``str``
    """
    try:
        file_info = demisto.getFilePath(attach_id)
        with open(file_info['path'], 'rb') as file_data:
            b64_encoded_data = base64.b64encode(file_data.read())
            file_size = os.path.getsize(file_info['path'])
            return b64_encoded_data, file_size, file_info['name']
    except Exception as e:
        raise Exception(f'Unable to read and decode in base 64 file with id {attach_id}', e)


def prepare_args(command, args):
    """
    Receives command and prepares the arguments for future usage.

    :type command: ``str``
    :param command: Command to execute

    :type args: ``dict``
    :param args: Demisto args

    :return: Prepared args
    :rtype: ``dict``
    """
    if command in ['msgraph-mail-create-draft', 'send-mail']:
        if args.get('htmlBody', None):
            email_body = args.get('htmlBody')
        else:
            email_body = args.get('body', '')
        return {
            'to_recipients': argToList(args.get('to')),
            'cc_recipients': argToList(args.get('cc')),
            'bcc_recipients': argToList(args.get('bcc')),
            'replyTo': argToList(args.get('replyTo')),
            'subject': args.get('subject', ''),
            'body': email_body,
            'body_type': args.get('body_type', 'html'),
            'flag': args.get('flag', 'notFlagged'),
            'importance': args.get('importance', 'Low'),
            'internet_message_headers': argToList(args.get('headers')),
            'attach_ids': argToList(args.get('attach_ids')),
            'attach_names': argToList(args.get('attach_names')),
            'attach_cids': argToList((args.get('attach_cids'))),
            'manual_attachments': args.get('manualAttachObj', [])
        }

    elif command == 'msgraph-mail-reply-to':
        return {
            'to_recipients': argToList(args.get('to')),
            'message_id': args.get('message_id', ''),
            'comment': args.get('comment'),
            'attach_ids': argToList(args.get('attach_ids')),
            'attach_names': argToList(args.get('attach_names')),
            'attach_cids': argToList((args.get('attach_cids')))
        }

    return args


def prepare_outputs_for_reply_mail_command(reply, email_to, message_id):
    reply.pop('attachments', None)
    to_recipients, cc_recipients, bcc_recipients = build_recipients_human_readable(reply)
    reply['toRecipients'] = to_recipients
    reply['ccRecipients'] = cc_recipients
    reply['bccRecipients'] = bcc_recipients
    reply['ID'] = message_id

    message_content = assign_params(**reply)
    human_readable = tableToMarkdown(f'Replied message was successfully sent to {", ".join(email_to)} .',
                                     message_content)

    return CommandResults(
        outputs_prefix="MicrosoftGraph",
        readable_output=human_readable,
        outputs_key_field="SentMail",
        outputs=message_content,
    )


def build_recipients_human_readable(message_content):
    to_recipients = []
    cc_recipients = []
    bcc_recipients = []

    for recipients_dict in message_content.get('toRecipients', {}):
        to_recipients.append(recipients_dict.get('emailAddress', {}).get('address'))

    for recipients_dict in message_content.get('ccRecipients', {}):
        cc_recipients.append(recipients_dict.get('emailAddress', {}).get('address'))

    for recipients_dict in message_content.get('bccRecipients', {}):
        bcc_recipients.append(recipients_dict.get('emailAddress', {}).get('address'))

    return to_recipients, cc_recipients, bcc_recipients


''' MICROSOFT GRAPH MAIL CLIENT '''


class MsGraphClient:
    """
    Microsoft Graph Mail Client enables authorized access to a user's Office 365 mail data in a personal account.
    """
    ITEM_ATTACHMENT = '#microsoft.graph.itemAttachment'
    FILE_ATTACHMENT = '#microsoft.graph.fileAttachment'
    CONTEXT_DRAFT_PATH = 'MicrosoftGraph.Draft(val.ID && val.ID == obj.ID)'
    CONTEXT_SENT_EMAIL_PATH = 'MicrosoftGraph.Email'

    def __init__(self, self_deployed, tenant_id, auth_and_token_url, enc_key, app_name, base_url, use_ssl, proxy,
                 ok_codes, refresh_token, mailbox_to_fetch, folder_to_fetch, first_fetch_interval, emails_fetch_limit,
                 auth_code, redirect_uri,
                 certificate_thumbprint: Optional[str] = None,
                 private_key: Optional[str] = None,
                 ):
        self.ms_client = MicrosoftClient(self_deployed=self_deployed, tenant_id=tenant_id, auth_id=auth_and_token_url,
                                         enc_key=enc_key, app_name=app_name, base_url=base_url, verify=use_ssl,
                                         proxy=proxy, ok_codes=ok_codes, refresh_token=refresh_token,
                                         auth_code=auth_code, redirect_uri=redirect_uri,
                                         grant_type=AUTHORIZATION_CODE, certificate_thumbprint=certificate_thumbprint,
                                         private_key=private_key)
        self._mailbox_to_fetch = mailbox_to_fetch
        self._folder_to_fetch = folder_to_fetch
        self._first_fetch_interval = first_fetch_interval
        self._emails_fetch_limit = emails_fetch_limit

    def _get_root_folder_children(self, user_id):
        """
        Get the root folder (Top Of Information Store) children collection.

        :type user_id: ``str``
        :param user_id: Mailbox address

        :raises: ``Exception``: No folders found under Top Of Information Store folder

        :return: List of root folder children
        rtype: ``list``
        """
        suffix_endpoint = f'users/{user_id}/mailFolders/msgfolderroot/childFolders?$top=250'
        root_folder_children = self.ms_client.http_request('GET', suffix_endpoint).get('value', None)
        if not root_folder_children:
            raise Exception("No folders found under Top Of Information Store folder")

        return root_folder_children

    def _get_folder_children(self, user_id, folder_id):
        """
        Get the folder collection under the specified folder.

        :type user_id ``str``
        :param user_id: Mailbox address

        :type folder_id: ``str``
        :param folder_id: Folder id

        :return: List of folders that contain basic folder information
        :rtype: ``list``
        """
        suffix_endpoint = f'users/{user_id}/mailFolders/{folder_id}/childFolders?$top=250'
        folder_children = self.ms_client.http_request('GET', suffix_endpoint).get('value', [])
        return folder_children

    def _get_folder_info(self, user_id, folder_id):
        """
        Returns folder information.

        :type user_id: ``str``
        :param user_id: Mailbox address

        :type folder_id: ``str``
        :param folder_id: Folder id

        :raises: ``Exception``: No info found for folder {folder id}

        :return: Folder information if found
        :rtype: ``dict``
        """

        suffix_endpoint = f'users/{user_id}/mailFolders/{folder_id}'
        folder_info = self.ms_client.http_request('GET', suffix_endpoint)
        if not folder_info:
            raise Exception(f'No info found for folder {folder_id}')
        return folder_info

    def _get_folder_by_path(self, user_id, folder_path):
        """
        Searches and returns basic folder information.

        Receives mailbox address and folder path (e.g Inbox/Phishing) and iteratively retrieves folders info until
        reaches the last folder of a path. In case that such folder exist, basic information that includes folder id,
        display name, parent folder id, child folders count, unread items count and total items count will be returned.

        :type user_id: ``str``
        :param user_id: Mailbox address

        :type folder_path: ``str``
        :param folder_path: Folder path of searched folder

        :raises: ``Exception``: No such folder exist: {folder path}

        :return: Folder information if found
        :rtype: ``dict``
        """
        folders_names = folder_path.replace('\\', '/').split('/')  # replaced backslash in original folder path

        # Optimization step in order to improve performance before iterating the folder path in order to skip API call
        # for getting Top of Information Store children collection if possible.
        if folders_names[0].lower() in WELL_KNOWN_FOLDERS:
            # check if first folder in the path is known folder in order to skip not necessary api call
            folder_id = WELL_KNOWN_FOLDERS[folders_names[0].lower()]  # get folder shortcut instead of using folder id
            if len(folders_names) == 1:  # in such case the folder path consist only from one well known folder
                return self._get_folder_info(user_id, folder_id)
            else:
                current_directory_level_folders = self._get_folder_children(user_id, folder_id)
                folders_names.pop(0)  # remove the first folder name from the path before iterating
        else:  # in such case the optimization step is skipped
            # current_directory_level_folders will be set to folders that are under Top Of Information Store (root)
            current_directory_level_folders = self._get_root_folder_children(user_id)

        for index, folder_name in enumerate(folders_names):
            # searching for folder in current_directory_level_folders list by display name or id
            found_folder = [f for f in current_directory_level_folders if
                            f.get('displayName', '').lower() == folder_name.lower() or f.get('id', '') == folder_name]

            if not found_folder:  # no folder found, return error
                raise Exception(f'No such folder exist: {folder_path}')
            found_folder = found_folder[0]  # found_folder will be list with only one element in such case

            if index == len(folders_names) - 1:  # reached the final folder in the path
                # skip get folder children step in such case
                return found_folder
            # didn't reach the end of the loop, set the current_directory_level_folders to folder children
            current_directory_level_folders = self._get_folder_children(user_id, found_folder.get('id', ''))

    def _fetch_last_emails(self, folder_id, last_fetch, exclude_ids):
        """
        Fetches emails from given folder that were modified after specific datetime (last_fetch).

        All fields are fetched for given email using select=* clause,
        for more information https://docs.microsoft.com/en-us/graph/query-parameters.
        The email will be excluded from returned results if it's id is presented in exclude_ids.
        Number of fetched emails is limited by _emails_fetch_limit parameter.
        The filtering and ordering is done based on modified time.

        :type folder_id: ``str``
        :param folder_id: Folder id

        :type last_fetch: ``dict``
        :param last_fetch: Previous fetch data

        :type exclude_ids: ``list``
        :param exclude_ids: List of previous fetch email ids to exclude in current run

        :return: Fetched emails and exclude ids list that contains the new ids of fetched emails
        :rtype: ``list`` and ``list``
        """
        target_modified_time = add_second_to_str_date(last_fetch)  # workaround to Graph API bug
        suffix_endpoint = f"/users/{self._mailbox_to_fetch}/mailFolders/{folder_id}/messages"
        params = {
            "$filter": f"receivedDateTime gt {target_modified_time}",
            "$orderby": "receivedDateTime asc",
            "$select": "*",
            "$top": self._emails_fetch_limit
        }

        fetched_emails = self.ms_client.http_request(
            'GET', suffix_endpoint, params=params
        ).get('value', [])[:self._emails_fetch_limit]

        if exclude_ids:  # removing emails in order to prevent duplicate incidents
            fetched_emails = [email for email in fetched_emails if email.get('id') not in exclude_ids]

        fetched_emails_ids = [email.get('id') for email in fetched_emails]
        return fetched_emails, fetched_emails_ids

    @staticmethod
    def _get_next_run_time(fetched_emails, start_time):
        """
        Returns received time of last email if exist, else utc time that was passed as start_time.

        The elements in fetched emails are ordered by modified time in ascending order,
        meaning the last element has the latest received time.

        :type fetched_emails: ``list``
        :param fetched_emails: List of fetched emails

        :type start_time: ``str``
        :param start_time: utc string of format Y-m-dTH:M:SZ

        :return: Returns str date of format Y-m-dTH:M:SZ
        :rtype: `str`
        """
        next_run_time = fetched_emails[-1].get('receivedDateTime') if fetched_emails else start_time

        return next_run_time

    @staticmethod
    def _get_recipient_address(email_address):
        """
        Receives dict of form  "emailAddress":{"name":"_", "address":"_"} and return the address

        :type email_address: ``dict``
        :param email_address: Recipient address

        :return: The address of recipient
        :rtype: ``str``
        """
        return email_address.get('emailAddress', {}).get('address', '')

    @staticmethod
    def _parse_email_as_labels(parsed_email):
        """
        Parses the email as incident labels.

        :type parsed_email: ``dict``
        :param parsed_email: The parsed email from which create incidents labels.

        :return: Incident labels
        :rtype: ``list``
        """
        labels = []

        for (key, value) in parsed_email.items():
            if key == 'Headers':
                headers_labels = [
                    {'type': 'Email/Header/{}'.format(header.get('name', '')), 'value': header.get('value', '')}
                    for header in value]
                labels.extend(headers_labels)
            elif key in ['To', 'Cc', 'Bcc']:
                recipients_labels = [{'type': f'Email/{key}', 'value': recipient} for recipient in value]
                labels.extend(recipients_labels)
            else:
                labels.append({'type': f'Email/{key}', 'value': f'{value}'})

        return labels

    @staticmethod
    def _parse_item_as_dict(email):
        """
        Parses basic data of email.

        Additional info https://docs.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0

        :type email: ``dict``
        :param email: Email to parse

        :return: Parsed email
        :rtype: ``dict``
        """
        parsed_email = {EMAIL_DATA_MAPPING[k]: v for (k, v) in email.items() if k in EMAIL_DATA_MAPPING}
        parsed_email['Headers'] = email.get('internetMessageHeaders', [])

        email_body = email.get('body', {}) or email.get('uniqueBody', {})
        parsed_email['Body'] = email_body.get('content', '')
        parsed_email['BodyType'] = email_body.get('contentType', '')

        parsed_email['Sender'] = MsGraphClient._get_recipient_address(email.get('sender', {}))
        parsed_email['From'] = MsGraphClient._get_recipient_address(email.get('from', {}))
        parsed_email['To'] = list(map(MsGraphClient._get_recipient_address, email.get('toRecipients', [])))
        parsed_email['Cc'] = list(map(MsGraphClient._get_recipient_address, email.get('ccRecipients', [])))
        parsed_email['Bcc'] = list(map(MsGraphClient._get_recipient_address, email.get('bccRecipients', [])))

        return parsed_email

    @staticmethod
    def _build_recipient_input(recipients):
        """
        Builds legal recipients list.

        :type recipients: ``list``
        :param recipients: List of recipients

        :return: List of email addresses recipients
        :rtype: ``list``
        """
        return [{'emailAddress': {'address': r}} for r in recipients] if recipients else []

    @staticmethod
    def _build_body_input(body, body_type):
        """
        Builds message body input.

        :type body: ``str``
        :param body: The body of the message

        :type body_type: The body type of the message, html or text.
        :param body_type:

        :return: The message body
        :rtype ``dict``
        """
        return {
            "content": body,
            "contentType": body_type
        }

    @staticmethod
    def _build_flag_input(flag):
        """
        Builds flag status of the message.

        :type flag: ``str``
        :param flag: The flag of the message

        :return: The flag status of the message
        :rtype ``dict``
        """
        return {'flagStatus': flag}

    @staticmethod
    def _build_headers_input(internet_message_headers):
        """
        Builds valid headers input.

        :type internet_message_headers: ``list``
        :param internet_message_headers: List of headers to build.

        :return: List of transformed headers
        :rtype: ``list``
        """
        return [{'name': kv[0], 'value': kv[1]} for kv in (h.split(':') for h in internet_message_headers)]

    @classmethod
    def _build_attachments_input(cls, ids, attach_names=None, is_inline=False):
        """
        Builds valid attachment input of the message. Is used for both in-line and regular attachments.

        :type ids: ``list``
        :param ids: List of uploaded to War Room files ids

        :type attach_names: ``list``
        :param attach_names: List of attachment name, not required.

        :type is_inline: ``bool``
        :param is_inline: Indicates whether the attachment is inline or not

        :return: List of valid attachments of message
        :rtype: ``list``
        """
        provided_names = bool(attach_names)

        if provided_names and len(ids) != len(attach_names):
            raise Exception("Invalid input, attach_ids and attach_names lists should be the same length.")

        file_attachments_result = []
        # in case that no attach names where provided, ids are zipped together and the attach_name value is ignored
        attachments = zip(ids, attach_names) if provided_names else zip(ids, ids)

        for attach_id, attach_name in attachments:
            b64_encoded_data, file_size, uploaded_file_name = read_file_and_encode64(attach_id)
            attachment = {
                '@odata.type': cls.FILE_ATTACHMENT,
                'contentBytes': b64_encoded_data.decode('utf-8'),
                'isInline': is_inline,
                'name': attach_name if provided_names else uploaded_file_name,
                'size': file_size,
                'contentId': attach_id,
            }
            file_attachments_result.append(attachment)

        return file_attachments_result

    @staticmethod
    def _build_file_attachments_input(attach_ids, attach_names, attach_cids, manual_attachments):
        """
        Builds both inline and regular attachments.

        :type attach_ids: ``list``
        :param attach_ids: List of uploaded to War Room regular attachments to send

        :type attach_names: ``list``
        :param attach_names: List of regular attachments names to send

        :type attach_cids: ``list``
        :param attach_cids: List of uploaded to War Room inline attachments to send

        :type manual_attachments: ``list``
        :param manual_attachments: List of manual attachments reports to send

        :return: List of both inline and regular attachments of the message
        :rtype: ``list``
        """
        regular_attachments = MsGraphClient._build_attachments_input(ids=attach_ids, attach_names=attach_names)
        inline_attachments = MsGraphClient._build_attachments_input(ids=attach_cids, is_inline=True)
        # collecting manual attachments info
        manual_att_ids = [os.path.basename(att['RealFileName']) for att in manual_attachments if 'RealFileName' in att]
        manual_att_names = [att['FileName'] for att in manual_attachments if 'FileName' in att]
        manual_report_attachments = MsGraphClient._build_attachments_input(ids=manual_att_ids,
                                                                           attach_names=manual_att_names)

        return regular_attachments + inline_attachments + manual_report_attachments

    @staticmethod
    def _build_message(to_recipients, cc_recipients, bcc_recipients, subject, body, body_type, flag, importance,
                       internet_message_headers, attach_ids, attach_names, attach_cids, manual_attachments, replyTo):
        """
        Builds valid message dict.
        For more information https://docs.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0
        """
        message = {
            'toRecipients': MsGraphClient._build_recipient_input(to_recipients),
            'ccRecipients': MsGraphClient._build_recipient_input(cc_recipients),
            'bccRecipients': MsGraphClient._build_recipient_input(bcc_recipients),
            'replyTo': MsGraphClient._build_recipient_input(replyTo),
            'subject': subject,
            'body': MsGraphClient._build_body_input(body=body, body_type=body_type),
            'bodyPreview': body[:255],
            'importance': importance,
            'flag': MsGraphClient._build_flag_input(flag),
            'attachments': MsGraphClient._build_file_attachments_input(attach_ids, attach_names, attach_cids,
                                                                       manual_attachments)
        }

        if internet_message_headers:
            message['internetMessageHeaders'] = MsGraphClient._build_headers_input(internet_message_headers)

        return message

    @staticmethod
    def _build_reply(to_recipients, comment, attach_ids, attach_names, attach_cids):
        """
        Builds the reply message that includes recipients to reply and reply message.

        :type to_recipients: ``list``
        :param to_recipients: The recipients list to reply

        :type comment: ``str``
        :param comment: The message to reply.

        :type attach_ids: ``list``
        :param attach_ids: List of uploaded to War Room regular attachments to send

        :type attach_names: ``list``
        :param attach_names: List of regular attachments names to send

        :type attach_cids: ``list``
        :param attach_cids: List of uploaded to War Room inline attachments to send

        :return: Returns legal reply message.
        :rtype: ``dict``
        """
        return {
            'message': {
                'toRecipients': MsGraphClient._build_recipient_input(to_recipients),
                'attachments': MsGraphClient._build_file_attachments_input(attach_ids, attach_names, attach_cids, [])
            },
            'comment': comment
        }

    def _get_attachment_mime(self, message_id, attachment_id):
        """
        Gets attachment mime.

        :type attachment_id: ``str``
        :param attachment_id: Attachment id to get MIME

        :return: The MIME of the attachment
        :rtype: ``str``
        """
        suffix_endpoint = f'users/{self._mailbox_to_fetch}/messages/{message_id}/attachments/{attachment_id}/$value'
        mime_content = self.ms_client.http_request('GET', suffix_endpoint, resp_type='text')

        return mime_content

    def _get_email_attachments(self, message_id):
        """
        Get email attachments  and upload to War Room.

        :type message_id: ``str``
        :param message_id: The email id to get attachments

        :return: List of uploaded to War Room data, uploaded file path and name
        :rtype: ``list``
        """

        attachment_results = []  # type: ignore
        suffix_endpoint = f'users/{self._mailbox_to_fetch}/messages/{message_id}/attachments'
        attachments = self.ms_client.http_request('Get', suffix_endpoint).get('value', [])

        for attachment in attachments:
            attachment_type = attachment.get('@odata.type', '')
            attachment_name = attachment.get('name', 'untitled_attachment')
            if attachment_type == self.FILE_ATTACHMENT:
                try:
                    attachment_content = base64.b64decode(attachment.get('contentBytes', ''))
                except Exception as e:  # skip the uploading file step
                    demisto.info(f"MS-Graph-Listener: failed in decoding base64 file attachment with error {str(e)}")
                    continue
            elif attachment_type == self.ITEM_ATTACHMENT:
                attachment_id = attachment.get('id', '')
                attachment_content = self._get_attachment_mime(message_id, attachment_id)
                attachment_name = f'{attachment_name}.eml'
            else:
                # skip attachments that are not of the previous types (type referenceAttachment)
                continue
            # upload the item/file attachment to War Room
            upload_file(attachment_name, attachment_content, attachment_results)

        return attachment_results

    def _parse_email_as_incident(self, email):
        """
        Parses fetched emails as incidents.

        :type email: ``dict``
        :param email: Fetched email to parse

        :return: Parsed email
        :rtype: ``dict``
        """
        parsed_email = MsGraphClient._parse_item_as_dict(email)

        # handling attachments of fetched email
        attachments = self._get_email_attachments(message_id=email.get('id', ''))
        if attachments:
            parsed_email['Attachments'] = attachments

        parsed_email['Mailbox'] = self._mailbox_to_fetch

        incident = {
            'name': parsed_email['Subject'],
            'details': email.get('bodyPreview', '') or parsed_email['Body'],
            'labels': MsGraphClient._parse_email_as_labels(parsed_email),
            'occurred': parsed_email['ModifiedTime'],
            'attachment': parsed_email.get('Attachments', []),
            'rawJSON': json.dumps(parsed_email)
        }

        return incident

    @logger
    def fetch_incidents(self, last_run):
        """
        Fetches emails from office 365 mailbox and creates incidents of parsed emails.

        :type last_run: ``dict``
        :param last_run:
            Previous fetch run data that holds the fetch time in utc Y-m-dTH:M:SZ format,
            ids of fetched emails, id and path of folder to fetch incidents from

        :return: Next run data and parsed fetched incidents
        :rtype: ``dict`` and ``list``
        """
        last_fetch = last_run.get('LAST_RUN_TIME')
        exclude_ids = last_run.get('LAST_RUN_IDS', [])
        last_run_folder_path = last_run.get('LAST_RUN_FOLDER_PATH')
        folder_path_changed = (last_run_folder_path != self._folder_to_fetch)

        if folder_path_changed:
            # detected folder path change, get new folder id
            folder_id = self._get_folder_by_path(self._mailbox_to_fetch, self._folder_to_fetch).get('id')
            demisto.info("MS-Graph-Listener: detected file path change, ignored last run.")
        else:
            # LAST_RUN_FOLDER_ID is stored in order to avoid calling _get_folder_by_path method in each fetch
            folder_id = last_run.get('LAST_RUN_FOLDER_ID')

        if not last_fetch or folder_path_changed:  # initialized fetch
            last_fetch, _ = parse_date_range(self._first_fetch_interval, date_format=DATE_FORMAT, utc=True)
            demisto.info(f"MS-Graph-Listener: initialize fetch and pull emails from date :{last_fetch}")

        fetched_emails, fetched_emails_ids = self._fetch_last_emails(folder_id=folder_id, last_fetch=last_fetch,
                                                                     exclude_ids=exclude_ids)
        incidents = list(map(self._parse_email_as_incident, fetched_emails))
        next_run_time = MsGraphClient._get_next_run_time(fetched_emails, last_fetch)
        next_run = {
            'LAST_RUN_TIME': next_run_time,
            'LAST_RUN_IDS': fetched_emails_ids,
            'LAST_RUN_FOLDER_ID': folder_id,
            'LAST_RUN_FOLDER_PATH': self._folder_to_fetch
        }
        demisto.info(f"MS-Graph-Listener: fetched {len(incidents)} incidents")

        return next_run, incidents

    def create_draft(self, **kwargs):
        """
        Creates draft message in user's mailbox, in draft folder.
        """
        suffix_endpoint = f'/users/{self._mailbox_to_fetch}/messages'
        draft = MsGraphClient._build_message(**kwargs)

        created_draft = self.ms_client.http_request('POST', suffix_endpoint, json_data=draft)
        parsed_draft = MsGraphClient._parse_item_as_dict(created_draft)
        human_readable = tableToMarkdown(f'Created draft with id: {parsed_draft.get("ID", "")}', parsed_draft)
        ec = {self.CONTEXT_DRAFT_PATH: parsed_draft}

        return human_readable, ec, created_draft

    def send_email(self, **kwargs):
        """
        Sends email from user's mailbox, the sent message will appear in Sent Items folder
        """
        from_address = kwargs.get('from', self._mailbox_to_fetch)
        suffix_endpoint = f'/users/{from_address}/sendMail'
        message_content = MsGraphClient._build_message(**kwargs)
        self.ms_client.http_request('POST', suffix_endpoint, json_data={'message': message_content},
                                    resp_type="text")

        message_content.pop('attachments', None)
        message_content.pop('internet_message_headers', None)
        human_readable = tableToMarkdown('Email was sent successfully.', message_content)
        ec = {self.CONTEXT_SENT_EMAIL_PATH: message_content}

        return human_readable, ec

    def reply_to(self, to_recipients, comment, message_id, attach_ids, attach_names, attach_cids):
        """
        Sends reply message to recipients.

        :type to_recipients: ``list``
        :param to_recipients: List of recipients to reply.

        :type comment: ``str``
        :param comment: The comment to send as a reply

        :type message_id: ``str``
        :param message_id: The message id to reply.

        :type attach_ids: ``list``
        :param attach_ids: List of uploaded to War Room regular attachments to send

        :type attach_names: ``list``
        :param attach_names: List of regular attachments names to send

        :type attach_cids: ``list``
        :param attach_cids: List of uploaded to War Room inline attachments to send

        :return: String representation of markdown message regarding successful message submission.
        rtype: ``str``
        """
        suffix_endpoint = f'/users/{self._mailbox_to_fetch}/messages/{message_id}/reply'
        reply = MsGraphClient._build_reply(to_recipients, comment, attach_ids, attach_names, attach_cids)
        self.ms_client.http_request('POST', suffix_endpoint, json_data=reply, resp_type="text")

        return f'### Replied to: {", ".join(to_recipients)} with comment: {comment}'

    def reply_mail(self, args):
        email_to = argToList(args.get('to'))
        email_from = args.get('from', self._mailbox_to_fetch)
        message_id = args.get('inReplyTo')
        email_body = args.get('body', "")
        email_subject = args.get('subject', "")
        email_subject = f'Re: {email_subject}'
        attach_ids = argToList(args.get('attachIDs'))
        email_cc = argToList(args.get('cc'))
        email_bcc = argToList(args.get('bcc'))
        html_body = args.get('htmlBody')
        attach_names = argToList(args.get('attachNames'))
        attach_cids = argToList(args.get('attachCIDs'))
        message_body = html_body or email_body

        suffix_endpoint = f'/users/{email_from}/messages/{message_id}/reply'
        reply = self.build_message_to_reply(email_to, email_cc, email_bcc, email_subject, message_body,
                                            attach_ids,
                                            attach_names, attach_cids)
        self.ms_client.http_request('POST', suffix_endpoint, json_data={'message': reply, 'comment': message_body},
                                    resp_type="text")

        return prepare_outputs_for_reply_mail_command(reply, email_to, message_id)

    def send_draft(self, draft_id):
        """
        Send draft message.

        :type draft_id: ``str``
        :param draft_id: Draft id to send.

        :return: String representation of markdown message regarding successful message submission.
        :rtype: ``str``
        """
        suffix_endpoint = f'/users/{self._mailbox_to_fetch}/messages/{draft_id}/send'
        self.ms_client.http_request('POST', suffix_endpoint, resp_type="text")

        return f'### Draft with: {draft_id} id was sent successfully.'

    @staticmethod
    def build_message_to_reply(to_recipients, cc_recipients, bcc_recipients, subject, email_body, attach_ids,
                               attach_names, attach_cids):
        """
        Builds a valid reply message dict.
        For more information https://docs.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0
        """
        return {
            'toRecipients': MsGraphClient._build_recipient_input(to_recipients),
            'ccRecipients': MsGraphClient._build_recipient_input(cc_recipients),
            'bccRecipients': MsGraphClient._build_recipient_input(bcc_recipients),
            'subject': subject,
            'bodyPreview': email_body[:255],
            'attachments': MsGraphClient._build_file_attachments_input(attach_ids, attach_names, attach_cids, [])
        }

    def list_mails(self, search: str = None, odata: str = None) -> Union[dict, list]:
        """Returning all mails from given user

        Args:
            user_id (str):
            search (str):
            odata (str):

        Returns:
            dict or list:
        """
        no_folder = f'/users/{self._mailbox_to_fetch}/messages'
        pages_to_pull = demisto.args().get('pages_to_pull', 1)
        page_size = demisto.args().get('page_size', 20)
        odata = f'{odata}&$top={page_size}' if odata else f'$top={page_size}'

        if search:
            # Data is being handled as a JSON so in cases the search phrase contains double quote ",
            # we should escape it.
            search = search.replace('"', '\\"')
            odata = f'{odata}&$search="{quote(search)}"'
        suffix = no_folder
        if odata:
            suffix += f'?{odata}'
        demisto.debug(f"URL suffix is {suffix}")
        response = self.ms_client.http_request('GET', suffix)
        return self.pages_puller(response, assert_pages(pages_to_pull))

    def pages_puller(self, response: dict, page_count: int) -> list:
        """ Gets first response from API and returns all pages

        Args:
            response (dict):
            page_count (int):

        Returns:
            list: list of all pages
        """
        responses = [response]
        for i in range(page_count - 1):
            next_link = response.get('@odata.nextLink')
            if next_link:
                response = self.ms_client.http_request('GET', full_url=next_link, url_suffix=None)
                responses.append(response)
            else:
                return responses
        return responses

    def test_connection(self):
        """
        Basic connection test instead of test-module.

        :return: Returns markdown string representation of success or Exception in case of login failure.
        rtype: ``str`` or Exception
        """
        suffix_endpoint = f'users/{self._mailbox_to_fetch}'
        user_response = self.ms_client.http_request('GET', suffix_endpoint)

        if user_response.get('mail') != '' and user_response.get('id') != '':
            return_outputs('```✅ Success!```')
        else:
            raise Exception("Failed validating the user.")


def assert_pages(pages: Union[str, int]) -> int:
    """

    Args:
        pages (str or int): pages need to pull in int or str

    Returns:
        int: default 1

    """
    if isinstance(pages, str) and pages.isdigit():
        return int(pages)
    elif isinstance(pages, int):
        return pages
    return 1


def list_mails_command(client: MsGraphClient, args):
    search = args.get('search')
    odata = args.get('odata')

    raw_response = client.list_mails(search=search, odata=odata)
    last_page_response = raw_response[len(raw_response) - 1]
    metadata = ''
    next_page = last_page_response.get('@odata.nextLink')
    if next_page:
        metadata = '\nPay attention there are more results than shown. For more data please ' \
                   'increase "pages_to_pull" argument'

    mail_context = build_mail_object(raw_response)
    entry_context = {}
    if mail_context:
        entry_context = {'MSGraphMail(val.ID === obj.ID)': mail_context}
        if next_page:
            # .NextPage.indexOf(\'http\')>=0 : will make sure the NextPage token will always be updated because it's a url
            entry_context['MSGraphMail(val.NextPage.indexOf(\'http\')>=0)'] = {'NextPage': next_page}

        # human_readable builder
        human_readable_header = f'{len(mail_context)} mails received {metadata}' if metadata \
            else f'Total of {len(mail_context)} mails received'
        human_readable = tableToMarkdown(
            human_readable_header,
            mail_context,
            headers=['Subject', 'From', 'Recipients', 'SendTime', 'ID', 'InternetMessageID']
        )
    else:
        human_readable = '### No mails were found'
    return_outputs(human_readable, entry_context, raw_response)


def build_mail_object(raw_response: Union[dict, list], get_body: bool = False) -> Union[dict, list]:
    """Building mail entry context
    Getting a list from build_mail_object

    Args:
        user_id (str): user id of the mail
        get_body (bool): should get body
        raw_response (dict or list): list of pages

    Returns:
        dict or list: output context
    """

    def build_mail(given_mail: dict) -> dict:
        """

        Args:
            given_mail (dict):

        Returns:
            dict:
        """
        # Dicts
        mail_properties = {
            'ID': 'id',
            'Created': 'createdDateTime',
            'LastModifiedTime': 'lastModifiedDateTime',
            'ReceivedTime': 'receivedDateTime',
            'SendTime': 'sentDateTime',
            'Categories': 'categories',
            'HasAttachments': 'hasAttachments',
            'Subject': 'subject',
            'IsDraft': 'isDraft',
            'Headers': 'internetMessageHeaders',
            'Flag': 'flag',
            'Importance': 'importance',
            'InternetMessageID': 'internetMessageId',
            'ConversationID': 'conversationId',
        }

        contact_properties = {
            'Sender': 'sender',
            'From': 'from',
            'Recipients': 'toRecipients',
            'CCRecipients': 'ccRecipients',
            'BCCRecipients': 'bccRecipients',
            'ReplyTo': 'replyTo'
        }

        # Create entry properties
        entry = {k: given_mail.get(v) for k, v in mail_properties.items()}

        # Create contacts properties
        entry.update(
            {k: build_contact(given_mail.get(v)) for k, v in contact_properties.items()}  # type: ignore
        )

        if get_body:
            entry['Body'] = given_mail.get('body', {}).get('content')
        return entry

    def build_contact(contacts: Union[dict, list, str]) -> object:
        """Building contact object

        Args:
            contacts (list or dict or str):

        Returns:
            dict or list[dict] or str or None: describing contact
        """
        if contacts:
            if isinstance(contacts, list):
                return [build_contact(contact) for contact in contacts]
            elif isinstance(contacts, dict):
                email = contacts.get('emailAddress')
                if email and isinstance(email, dict):
                    return {
                        'Name': email.get('name'),
                        'Address': email.get('address')
                    }
        return None

    mails_list = list()
    if isinstance(raw_response, list):  # response from list_emails_command
        for page in raw_response:
            # raw_response is a list containing multiple pages or one page
            # if value is not empty, there are emails in the page
            value = page.get('value')
            if value:
                for mail in value:
                    mails_list.append(build_mail(mail))
    elif isinstance(raw_response, dict):  # response from get_message_command
        return build_mail(raw_response)
    return mails_list


def main():
    """ COMMANDS MANAGER / SWITCH PANEL """
    params = demisto.params()

    self_deployed = params.get('self_deployed', False)

    # params related to common instance configuration
    base_url = 'https://graph.microsoft.com/v1.0/'
    use_ssl = not params.get('insecure', False)
    proxy = params.get('proxy', False)
    ok_codes = (200, 201, 202)
    refresh_token = params.get('refresh_token', '')
    auth_and_token_url = params.get('auth_id', '')
    enc_key = params.get('enc_key', '')
    certificate_thumbprint = params.get('certificate_thumbprint')
    private_key = params.get('private_key')
    app_name = 'ms-graph-mail-listener'

    if not self_deployed and not enc_key:
        raise DemistoException('Key must be provided. For further information see '
                               'https://xsoar.pan.dev/docs/reference/articles/microsoft-integrations---authentication')
    elif not enc_key and not (certificate_thumbprint and private_key):
        raise DemistoException('Key or Certificate Thumbprint and Private Key must be provided.')

    # params related to mailbox to fetch incidents
    mailbox_to_fetch = params.get('mailbox_to_fetch', '')
    folder_to_fetch = params.get('folder_to_fetch', 'Inbox')
    first_fetch_interval = params.get('first_fetch', '15 minutes')
    emails_fetch_limit = int(params.get('fetch_limit', '50'))

    # params related to self deployed
    tenant_id = refresh_token if self_deployed else ''

    # params related to oproxy
    # In case the script is running for the first time, refresh token is retrieved from integration parameters,
    # in other case it's retrieved from integration context.
    refresh_token = get_integration_context().get('current_refresh_token') or refresh_token

    client = MsGraphClient(self_deployed, tenant_id, auth_and_token_url, enc_key, app_name, base_url, use_ssl, proxy,
                           ok_codes, refresh_token, mailbox_to_fetch, folder_to_fetch, first_fetch_interval,
                           emails_fetch_limit, auth_code=params.get('auth_code', ''), private_key=private_key,
                           redirect_uri=params.get('redirect_uri', ''), certificate_thumbprint=certificate_thumbprint)
    try:
        command = demisto.command()
        args = prepare_args(command, demisto.args())
        LOG(f'Command being called is {command}')

        if command == 'test-module':
            # cannot use test module due to the lack of ability to set refresh token to integration context
            raise Exception("Please use !msgraph-mail-test instead")
        if command == 'msgraph-mail-test':
            client.test_connection()
        if command == 'fetch-incidents':
            next_run, incidents = client.fetch_incidents(demisto.getLastRun())
            demisto.setLastRun(next_run)
            demisto.incidents(incidents)
        elif command == 'msgraph-mail-create-draft':
            human_readable, ec, raw_response = client.create_draft(**args)
            return_outputs(human_readable, ec, raw_response)
        elif command == 'msgraph-mail-reply-to':
            human_readable = client.reply_to(**args)  # pylint: disable=E1123
            return_outputs(human_readable)
        elif command == 'msgraph-mail-send-draft':
            human_readable = client.send_draft(**args)  # pylint: disable=E1123
            return_outputs(human_readable)
        elif command == 'send-mail':
            human_readable, ec = client.send_email(**args)
            return_outputs(human_readable, ec)
        elif command == 'reply-mail':
            return_results(client.reply_mail(args))
        elif command == 'msgraph-mail-list-emails':
            return_results(list_mails_command(client, args))
    except Exception as e:
        return_error(str(e))


### GENERATED CODE ###: from MicrosoftApiModule import *  # noqa: E402
# This code was inserted in place of an API module.
register_module_line('MicrosoftApiModule', 'start', __line__(), wrapper=-3)


class Scopes:
    graph = 'https://graph.microsoft.com/.default'
    security_center = 'https://api.securitycenter.windows.com/.default'
    security_center_apt_service = 'https://securitycenter.onmicrosoft.com/windowsatpservice/.default'
    management_azure = 'https://management.azure.com/.default'


# authorization types
OPROXY_AUTH_TYPE = 'oproxy'
SELF_DEPLOYED_AUTH_TYPE = 'self_deployed'

# grant types in self-deployed authorization
CLIENT_CREDENTIALS = 'client_credentials'
AUTHORIZATION_CODE = 'authorization_code'
REFRESH_TOKEN = 'refresh_token'  # guardrails-disable-line
DEVICE_CODE = 'urn:ietf:params:oauth:grant-type:device_code'
REGEX_SEARCH_URL = r'(?P<url>https?://[^\s]+)'
SESSION_STATE = 'session_state'
TOKEN_RETRIEVAL_ENDPOINTS = {
    'com': 'https://login.microsoftonline.com',
    'gcc-high': 'https://login.microsoftonline.us',
    'dod': 'https://login.microsoftonline.us',
    'de': 'https://login.microsoftonline.de',
    'cn': 'https://login.chinacloudapi.cn',
}
GRAPH_ENDPOINTS = {
    'com': 'https://graph.microsoft.com',
    'gcc-high': 'https://graph.microsoft.us',
    'dod': 'https://dod-graph.microsoft.us',
    'de': 'https://graph.microsoft.de',
    'cn': 'https://microsoftgraph.chinacloudapi.cn'
}
GRAPH_BASE_ENDPOINTS = {
    'https://graph.microsoft.com': 'com',
    'https://graph.microsoft.us': 'gcc-high',
    'https://dod-graph.microsoft.us': 'dod',
    'https://graph.microsoft.de': 'de',
    'https://microsoftgraph.chinacloudapi.cn': 'cn'
}


class MicrosoftClient(BaseClient):
    def __init__(self, tenant_id: str = '',
                 auth_id: str = '',
                 enc_key: Optional[str] = '',
                 token_retrieval_url: str = '{endpoint}/{tenant_id}/oauth2/v2.0/token',
                 app_name: str = '',
                 refresh_token: str = '',
                 auth_code: str = '',
                 scope: str = '{graph_endpoint}/.default',
                 grant_type: str = CLIENT_CREDENTIALS,
                 redirect_uri: str = 'https://localhost/myapp',
                 resource: Optional[str] = '',
                 multi_resource: bool = False,
                 resources: List[str] = None,
                 verify: bool = True,
                 self_deployed: bool = False,
                 timeout: Optional[int] = None,
                 azure_ad_endpoint: str = '{endpoint}',
                 endpoint: str = 'com',
                 certificate_thumbprint: Optional[str] = None,
                 private_key: Optional[str] = None,
                 *args, **kwargs):
        """
        Microsoft Client class that implements logic to authenticate with oproxy or self deployed applications.
        It also provides common logic to handle responses from Microsoft.
        Args:
            tenant_id: If self deployed it's the tenant for the app url, otherwise (oproxy) it's the token
            auth_id: If self deployed it's the client id, otherwise (oproxy) it's the auth id and may also
            contain the token url
            enc_key: If self deployed it's the client secret, otherwise (oproxy) it's the encryption key
            scope: The scope of the application (only if self deployed)
            resource: The resource of the application (only if self deployed)
            multi_resource: Where or not module uses a multiple resources (self-deployed, auth_code grant type only)
            resources: Resources of the application (for multi-resource mode)
            verify: Demisto insecure parameter
            self_deployed: Indicates whether the integration mode is self deployed or oproxy
            certificate_thumbprint: Certificate's thumbprint that's associated to the app
            private_key: Private key of the certificate
        """
        super().__init__(verify=verify, *args, **kwargs)  # type: ignore[misc]
        self.endpoint = endpoint
        if not self_deployed:
            auth_id_and_token_retrieval_url = auth_id.split('@')
            auth_id = auth_id_and_token_retrieval_url[0]
            if len(auth_id_and_token_retrieval_url) != 2:
                self.token_retrieval_url = 'https://oproxy.demisto.ninja/obtain-token'  # guardrails-disable-line
            else:
                self.token_retrieval_url = auth_id_and_token_retrieval_url[1]

            self.app_name = app_name
            self.auth_id = auth_id
            self.enc_key = enc_key
            self.tenant_id = tenant_id
            self.refresh_token = refresh_token

        else:
            self.token_retrieval_url = token_retrieval_url.format(tenant_id=tenant_id,
                                                                  endpoint=TOKEN_RETRIEVAL_ENDPOINTS[self.endpoint])
            self.client_id = auth_id
            self.client_secret = enc_key
            self.tenant_id = tenant_id
            self.auth_code = auth_code
            self.grant_type = grant_type
            self.resource = resource
            self.scope = scope.format(graph_endpoint=GRAPH_ENDPOINTS[self.endpoint])
            self.redirect_uri = redirect_uri
            if certificate_thumbprint and private_key:
                try:
                    import msal  # pylint: disable=E0401
                    self.jwt = msal.oauth2cli.assertion.JwtAssertionCreator(
                        private_key,
                        'RS256',
                        certificate_thumbprint
                    ).create_normal_assertion(audience=self.token_retrieval_url, issuer=self.client_id)
                except ModuleNotFoundError:
                    raise DemistoException('Unable to use certificate authentication because `msal` is missing.')
            else:
                self.jwt = None

        self.auth_type = SELF_DEPLOYED_AUTH_TYPE if self_deployed else OPROXY_AUTH_TYPE
        self.verify = verify
        self.azure_ad_endpoint = azure_ad_endpoint.format(endpoint=TOKEN_RETRIEVAL_ENDPOINTS[self.endpoint])
        self.timeout = timeout  # type: ignore

        self.multi_resource = multi_resource
        if self.multi_resource:
            self.resources = resources if resources else []
            self.resource_to_access_token: Dict[str, str] = {}

    def http_request(
            self, *args, resp_type='json', headers=None,
            return_empty_response=False, scope: Optional[str] = None,
            resource: str = '', **kwargs):
        """
        Overrides Base client request function, retrieves and adds to headers access token before sending the request.

        Args:
            resp_type: Type of response to return. will be ignored if `return_empty_response` is True.
            headers: Headers to add to the request.
            return_empty_response: Return the response itself if the return_code is 206.
            scope: A scope to request. Currently will work only with self-deployed app.
            resource (str): The resource identifier for which the generated token will have access to.
        Returns:
            Response from api according to resp_type. The default is `json` (dict or list).
        """
        if 'ok_codes' not in kwargs and not self._ok_codes:
            kwargs['ok_codes'] = (200, 201, 202, 204, 206, 404)
        token = self.get_access_token(resource=resource, scope=scope)
        default_headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        if headers:
            default_headers.update(headers)

        if self.timeout:
            kwargs['timeout'] = self.timeout

        response = super()._http_request(  # type: ignore[misc]
            *args, resp_type="response", headers=default_headers, **kwargs)

        # 206 indicates Partial Content, reason will be in the warning header.
        # In that case, logs with the warning header will be written.
        if response.status_code == 206:
            demisto.debug(str(response.headers))
        is_response_empty_and_successful = (response.status_code == 204)
        if is_response_empty_and_successful and return_empty_response:
            return response

        # Handle 404 errors instead of raising them as exceptions:
        if response.status_code == 404:
            try:
                error_message = response.json()
            except Exception:
                error_message = 'Not Found - 404 Response'
            raise NotFoundError(error_message)

        try:
            if resp_type == 'json':
                return response.json()
            if resp_type == 'text':
                return response.text
            if resp_type == 'content':
                return response.content
            if resp_type == 'xml':
                ET.parse(response.text)
            return response
        except ValueError as exception:
            raise DemistoException('Failed to parse json object from response: {}'.format(response.content), exception)

    def get_access_token(self, resource: str = '', scope: Optional[str] = None) -> str:
        """
        Obtains access and refresh token from oproxy server or just a token from a self deployed app.
        Access token is used and stored in the integration context
        until expiration time. After expiration, new refresh token and access token are obtained and stored in the
        integration context.

        Args:
            resource (str): The resource identifier for which the generated token will have access to.
            scope (str): A scope to get instead of the default on the API.

        Returns:
            str: Access token that will be added to authorization header.
        """
        integration_context = get_integration_context()
        refresh_token = integration_context.get('current_refresh_token', '')
        # Set keywords. Default without the scope prefix.
        access_token_keyword = f'{scope}_access_token' if scope else 'access_token'
        valid_until_keyword = f'{scope}_valid_until' if scope else 'valid_until'

        if self.multi_resource:
            access_token = integration_context.get(resource)
        else:
            access_token = integration_context.get(access_token_keyword)

        valid_until = integration_context.get(valid_until_keyword)

        if access_token and valid_until:
            if self.epoch_seconds() < valid_until:
                return access_token

        if self.auth_type == OPROXY_AUTH_TYPE:
            if self.multi_resource:
                for resource_str in self.resources:
                    access_token, expires_in, refresh_token = self._oproxy_authorize(resource_str)
                    self.resource_to_access_token[resource_str] = access_token
                    self.refresh_token = refresh_token
            else:
                access_token, expires_in, refresh_token = self._oproxy_authorize(scope=scope)

        else:
            access_token, expires_in, refresh_token = self._get_self_deployed_token(
                refresh_token, scope, integration_context)
        time_now = self.epoch_seconds()
        time_buffer = 5  # seconds by which to shorten the validity period
        if expires_in - time_buffer > 0:
            # err on the side of caution with a slightly shorter access token validity period
            expires_in = expires_in - time_buffer
        valid_until = time_now + expires_in
        integration_context.update({
            access_token_keyword: access_token,
            valid_until_keyword: valid_until,
            'current_refresh_token': refresh_token
        })

        # Add resource access token mapping
        if self.multi_resource:
            integration_context.update(self.resource_to_access_token)

        set_integration_context(integration_context)

        if self.multi_resource:
            return self.resource_to_access_token[resource]

        return access_token

    def _oproxy_authorize(self, resource: str = '', scope: Optional[str] = None) -> Tuple[str, int, str]:
        """
        Gets a token by authorizing with oproxy.
        Args:
            scope: A scope to add to the request. Do not use it.
            resource: Resource to get.
        Returns:
            tuple: An access token, its expiry and refresh token.
        """
        content = self.refresh_token or self.tenant_id
        headers = self._add_info_headers()
        oproxy_response = requests.post(
            self.token_retrieval_url,
            headers=headers,
            json={
                'app_name': self.app_name,
                'registration_id': self.auth_id,
                'encrypted_token': self.get_encrypted(content, self.enc_key),
                'scope': scope,
                'resource': resource
            },
            verify=self.verify
        )

        if not oproxy_response.ok:
            msg = 'Error in authentication. Try checking the credentials you entered.'
            try:
                demisto.info('Authentication failure from server: {} {} {}'.format(
                    oproxy_response.status_code, oproxy_response.reason, oproxy_response.text))
                err_response = oproxy_response.json()
                server_msg = err_response.get('message')
                if not server_msg:
                    title = err_response.get('title')
                    detail = err_response.get('detail')
                    if title:
                        server_msg = f'{title}. {detail}'
                    elif detail:
                        server_msg = detail
                if server_msg:
                    msg += ' Server message: {}'.format(server_msg)
            except Exception as ex:
                demisto.error('Failed parsing error response - Exception: {}'.format(ex))
            raise Exception(msg)
        try:
            gcloud_function_exec_id = oproxy_response.headers.get('Function-Execution-Id')
            demisto.info(f'Google Cloud Function Execution ID: {gcloud_function_exec_id}')
            parsed_response = oproxy_response.json()
        except ValueError:
            raise Exception(
                'There was a problem in retrieving an updated access token.\n'
                'The response from the Oproxy server did not contain the expected content.'
            )

        return (parsed_response.get('access_token', ''), parsed_response.get('expires_in', 3595),
                parsed_response.get('refresh_token', ''))

    def _get_self_deployed_token(self,
                                 refresh_token: str = '',
                                 scope: Optional[str] = None,
                                 integration_context: Optional[dict] = None
                                 ) -> Tuple[str, int, str]:
        if self.grant_type == AUTHORIZATION_CODE:
            if not self.multi_resource:
                return self._get_self_deployed_token_auth_code(refresh_token, scope=scope)
            else:
                expires_in = -1  # init variable as an int
                for resource in self.resources:
                    access_token, expires_in, refresh_token = self._get_self_deployed_token_auth_code(refresh_token,
                                                                                                      resource)
                    self.resource_to_access_token[resource] = access_token

                return '', expires_in, refresh_token
        elif self.grant_type == DEVICE_CODE:
            return self._get_token_device_code(refresh_token, scope, integration_context)
        else:
            # by default, grant_type is CLIENT_CREDENTIALS
            if self.multi_resource:
                expires_in = -1  # init variable as an int
                for resource in self.resources:
                    access_token, expires_in, refresh_token = self._get_self_deployed_token_client_credentials(
                        resource=resource)
                    self.resource_to_access_token[resource] = access_token
                return '', expires_in, refresh_token
            return self._get_self_deployed_token_client_credentials(scope=scope)

    def _get_self_deployed_token_client_credentials(self, scope: Optional[str] = None,
                                                    resource: Optional[str] = None) -> Tuple[str, int, str]:
        """
        Gets a token by authorizing a self deployed Azure application in client credentials grant type.

        Args:
            scope: A scope to add to the headers. Else will get self.scope.
            resource: A resource to add to the headers. Else will get self.resource.
        Returns:
            tuple: An access token and its expiry.
        """
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': CLIENT_CREDENTIALS
        }

        if self.jwt:
            data.pop('client_secret', None)
            data['client_assertion_type'] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            data['client_assertion'] = self.jwt

        # Set scope.
        if self.scope or scope:
            data['scope'] = scope if scope else self.scope

        if self.resource or resource:
            data['resource'] = resource or self.resource  # type: ignore

        response_json: dict = {}
        try:
            response = requests.post(self.token_retrieval_url, data, verify=self.verify)
            if response.status_code not in {200, 201}:
                return_error(f'Error in Microsoft authorization. Status: {response.status_code},'
                             f' body: {self.error_parser(response)}')
            response_json = response.json()
        except Exception as e:
            return_error(f'Error in Microsoft authorization: {str(e)}')

        access_token = response_json.get('access_token', '')
        expires_in = int(response_json.get('expires_in', 3595))

        return access_token, expires_in, ''

    def _get_self_deployed_token_auth_code(
            self, refresh_token: str = '', resource: str = '', scope: Optional[str] = None) -> Tuple[str, int, str]:
        """
        Gets a token by authorizing a self deployed Azure application.
        Returns:
            tuple: An access token, its expiry and refresh token.
        """
        data = assign_params(
            client_id=self.client_id,
            client_secret=self.client_secret,
            resource=self.resource if not resource else resource,
            redirect_uri=self.redirect_uri
        )

        if self.jwt:
            data.pop('client_secret', None)
            data['client_assertion_type'] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            data['client_assertion'] = self.jwt

        if scope:
            data['scope'] = scope

        refresh_token = refresh_token or self._get_refresh_token_from_auth_code_param()
        if refresh_token:
            data['grant_type'] = REFRESH_TOKEN
            data['refresh_token'] = refresh_token
        else:
            if SESSION_STATE in self.auth_code:
                raise ValueError('Malformed auth_code parameter: Please copy the auth code from the redirected uri '
                                 'without any additional info and without the "session_state" query parameter.')
            data['grant_type'] = AUTHORIZATION_CODE
            data['code'] = self.auth_code

        response_json: dict = {}
        try:
            response = requests.post(self.token_retrieval_url, data, verify=self.verify)
            if response.status_code not in {200, 201}:
                return_error(f'Error in Microsoft authorization. Status: {response.status_code},'
                             f' body: {self.error_parser(response)}')
            response_json = response.json()
        except Exception as e:
            return_error(f'Error in Microsoft authorization: {str(e)}')

        access_token = response_json.get('access_token', '')
        expires_in = int(response_json.get('expires_in', 3595))
        refresh_token = response_json.get('refresh_token', '')

        return access_token, expires_in, refresh_token

    def _get_token_device_code(
            self, refresh_token: str = '', scope: Optional[str] = None, integration_context: Optional[dict] = None
    ) -> Tuple[str, int, str]:
        """
        Gets a token by authorizing a self deployed Azure application.

        Returns:
            tuple: An access token, its expiry and refresh token.
        """
        data = {
            'client_id': self.client_id,
            'scope': scope
        }

        if refresh_token:
            data['grant_type'] = REFRESH_TOKEN
            data['refresh_token'] = refresh_token
        else:
            data['grant_type'] = DEVICE_CODE
            if integration_context:
                data['code'] = integration_context.get('device_code')

        response_json: dict = {}
        try:
            response = requests.post(self.token_retrieval_url, data, verify=self.verify)
            if response.status_code not in {200, 201}:
                return_error(f'Error in Microsoft authorization. Status: {response.status_code},'
                             f' body: {self.error_parser(response)}')
            response_json = response.json()
        except Exception as e:
            return_error(f'Error in Microsoft authorization: {str(e)}')

        access_token = response_json.get('access_token', '')
        expires_in = int(response_json.get('expires_in', 3595))
        refresh_token = response_json.get('refresh_token', '')

        return access_token, expires_in, refresh_token

    def _get_refresh_token_from_auth_code_param(self) -> str:
        refresh_prefix = "refresh_token:"
        if self.auth_code.startswith(refresh_prefix):  # for testing we allow setting the refresh token directly
            demisto.debug("Using refresh token set as auth_code")
            return self.auth_code[len(refresh_prefix):]
        return ''

    @staticmethod
    def error_parser(error: requests.Response) -> str:
        """

        Args:
            error (requests.Response): response with error

        Returns:
            str: string of error

        """
        try:
            response = error.json()
            demisto.error(str(response))
            inner_error = response.get('error', {})
            if isinstance(inner_error, dict):
                err_str = f"{inner_error.get('code')}: {inner_error.get('message')}"
            else:
                err_str = inner_error
            if err_str:
                return err_str
            # If no error message
            raise ValueError
        except ValueError:
            return error.text

    @staticmethod
    def epoch_seconds(d: datetime = None) -> int:
        """
        Return the number of seconds for given date. If no date, return current.

        Args:
            d (datetime): timestamp
        Returns:
             int: timestamp in epoch
        """
        if not d:
            d = MicrosoftClient._get_utcnow()
        return int((d - MicrosoftClient._get_utcfromtimestamp(0)).total_seconds())

    @staticmethod
    def _get_utcnow() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _get_utcfromtimestamp(_time) -> datetime:
        return datetime.utcfromtimestamp(_time)

    @staticmethod
    def get_encrypted(content: str, key: Optional[str]) -> str:
        """
        Encrypts content with encryption key.
        Args:
            content: Content to encrypt
            key: encryption key from oproxy

        Returns:
            timestamp: Encrypted content
        """

        def create_nonce():
            return os.urandom(12)

        def encrypt(string, enc_key):
            """
            Encrypts string input with encryption key.
            Args:
                string: String to encrypt
                enc_key: Encryption key

            Returns:
                bytes: Encrypted value
            """
            # String to bytes
            try:
                enc_key = base64.b64decode(enc_key)
            except Exception as err:
                return_error(f"Error in Microsoft authorization: {str(err)}"
                             f" Please check authentication related parameters.", error=traceback.format_exc())

            # Create key
            aes_gcm = AESGCM(enc_key)
            # Create nonce
            nonce = create_nonce()
            # Create ciphered data
            data = string.encode()
            ct = aes_gcm.encrypt(nonce, data, None)
            return base64.b64encode(nonce + ct)

        now = MicrosoftClient.epoch_seconds()
        encrypted = encrypt(f'{now}:{content}', key).decode('utf-8')
        return encrypted

    @staticmethod
    def _add_info_headers() -> Dict[str, str]:
        # pylint: disable=no-member
        headers = {}
        try:
            headers = get_x_content_info_headers()
        except Exception as e:
            demisto.error('Failed getting integration info: {}'.format(str(e)))

        return headers

    def device_auth_request(self) -> dict:
        response_json = {}
        try:
            response = requests.post(
                url=f'{self.azure_ad_endpoint}/organizations/oauth2/v2.0/devicecode',
                data={
                    'client_id': self.client_id,
                    'scope': self.scope
                },
                verify=self.verify
            )
            if not response.ok:
                return_error(f'Error in Microsoft authorization. Status: {response.status_code},'
                             f' body: {self.error_parser(response)}')
            response_json = response.json()
        except Exception as e:
            return_error(f'Error in Microsoft authorization: {str(e)}')
        set_integration_context({'device_code': response_json.get('device_code')})
        return response_json

    def start_auth(self, complete_command: str) -> str:
        response = self.device_auth_request()
        message = response.get('message', '')
        re_search = re.search(REGEX_SEARCH_URL, message)
        url = re_search.group('url') if re_search else None
        user_code = response.get('user_code')

        return f"""### Authorization instructions
1. To sign in, use a web browser to open the page [{url}]({url})
and enter the code **{user_code}** to authenticate.
2. Run the **{complete_command}** command in the War Room."""


class NotFoundError(Exception):
    """Exception raised for 404 - Not Found errors.

    Attributes:
        message -- explanation of the error
    """

    def __init__(self, message):
        self.message = message


register_module_line('MicrosoftApiModule', 'end', __line__(), wrapper=1)
### END GENERATED CODE ###

if __name__ in ['__main__', '__builtin__', 'builtins']:
    main()

register_module_line('Microsoft Graph Mail Single User', 'end', __line__())
