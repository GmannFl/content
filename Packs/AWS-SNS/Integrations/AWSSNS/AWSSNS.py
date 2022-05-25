import boto3
import demistomock as demisto  # noqa: F401
from botocore.config import Config
from CommonServerPython import *  # noqa: F401

register_module_line('AWS - SNS', 'start', __line__())


def create_entry(title, data, ec):
    return {
        'ContentsFormat': formats['json'],
        'Type': entryTypes['note'],
        'Contents': data,
        'ReadableContentsFormat': formats['markdown'],
        'HumanReadable': tableToMarkdown(title, data) if data else 'No result were found',
        'EntryContext': ec
    }


def raise_error(error):
    return {
        'Type': entryTypes['error'],
        'ContentsFormat': formats['text'],
        'Contents': str(error)
    }


def create_subscription(args, client):
    try:
        attributes = {}
        kwargs = {
            'TopicArn': args.get('topicArn'),
            'Protocol': args.get('protocol')
        }
        if args.get('endpoint') is not None:
            kwargs.update({'Endpoint': args.get('endpoint')})
        if args.get('returnSubscriptionArn') is not None:
            kwargs.update({'ReturnSubscriptionArn': bool(args.get('returnSubscriptionArn'))})

        if args.get('deliveryPolicy') is not None:
            attributes.update({'DeliveryPolicy': args.get('deliveryPolicy')})
        if args.get('filterPolicy') is not None:
            attributes.update({'FilterPolicy': args.get('filterPolicy')})
        if args.get('rawMessageDelivery') is not None:
            attributes.update({'RawMessageDelivery': args.get('rawMessageDelivery')})
        if args.get('redrivePolicy') is not None:
            attributes.update({'RedrivePolicy': args.get('RedrivePolicy')})
        if args.get('subscriptionRoleArn') is not None:
            attributes.update({'SubscriptionRoleArn': args.get('subscriptionRoleArn')})
        if attributes:
            kwargs.update({'Attributes': attributes})

        response = client.subscribe(**kwargs)
        data = ({'SubscriptionArn': response['SubscriptionArn']})

        ec = {'AWS.SNS.Subscriptions': data}
        return create_entry('AWS SNS Subscriptions', data, ec)

    except Exception as e:
        return raise_error(e)


def list_topics(args, client):
    try:
        data = []
        kwargs = {}
        if args.get('nextToken') is not None:
            kwargs.update({'NextToken': args.get('nextToken')})
        response = client.list_topics(**kwargs)
        for topic in response['Topics']:
            data.append({'TopicArn': topic})

        ec = {'AWS.SNS.Topics': data}
        return create_entry('AWS SNS Topics', data, ec)

    except Exception as e:
        return raise_error(e)


def list_subscriptions_by_topic(args, client):
    try:
        data = []
        kwargs = {}
        if args.get('topicArn') is not None:
            kwargs.update({'TopicArn': args.get('topicArn')})
        if args.get('nextToken') is not None:
            kwargs.update({'NextToken': args.get('nextToken')})
        response = client.list_subscriptions_by_topic(**kwargs)
        for subscription in response['Subscriptions']:
            data.append({'SubscriptionArn': subscription['SubscriptionArn']})

        ec = {'AWS.SNS.Subscriptions': data}
        return create_entry('AWS SNS Subscriptions', data, ec)

    except Exception as e:
        return raise_error(e)


def send_message(args, client):
    try:
        data = []
        kwargs = {
            'Message': args.get('message')
        }

        if args.get('topicArn') is not None:
            kwargs.update({'TopicArn': args.get('topicArn')})
        if args.get('targetArn') is not None:
            kwargs.update({'TargetArn': args.get('targetArn')})
        if args.get('phoneNumber') is not None:
            kwargs.update({'PhoneNumber': args.get('phoneNumber')})
        if args.get('subject') is not None:
            kwargs.update({'Subject': args.get('subject')})
        if args.get('messageStructure') is not None:
            kwargs.update({'MessageStructure': args.get('messageStructure')})
        if args.get('messageDeduplicationId') is not None:
            kwargs.update({'MessageDeduplicationId': args.get('messageDeduplicationId')})
        if args.get('messageGroupId') is not None:
            kwargs.update({'MessageGroupId': args.get('messageGroupId')})

        response = client.publish(**kwargs)
        data.append({'MessageId': response['MessageId']})
        ec = {'AWS.SNS.SentMessages': data}
        return create_entry('AWS SNS sent messages', data, ec)

    except Exception as e:
        return raise_error(e)


def create_topic(args, client):
    try:
        attributes = {}
        kwargs = {'Name': args.get('topicName')}
        if args.get('deliveryPolicy') is not None:
            attributes.update({'DeliveryPolicy': args.get('deliveryPolicy')})
        if args.get('displayName') is not None:
            attributes.update({'DisplayName': args.get('displayName')})
        if args.get('fifoTopic') is not None:
            attributes.update({'FifoTopic': bool(args.get('fifoTopic'))})
        if args.get('policy') is not None:
            attributes.update({'policy': args.get('Policy')})
        if args.get('kmsMasterKeyId') is not None:
            attributes.update({'KmsMasterKeyId': args.get('kmsMasterKeyId')})
        if args.get('contentBasedDeduplication') is not None:
            attributes.update({'ContentBasedDeduplication': args.get('contentBasedDeduplication')})
        if attributes:
            kwargs.update({'Attributes': attributes})

        response = client.create_topic(**kwargs)
        data = ({'ARN': response['TopicArn']})
        ec = {'AWS.SNS.Topic': data}
        return create_entry('AWS SNS Topic', data, ec)

    except Exception as e:
        return raise_error(e)


def delete_topic(args, client):
    try:
        response = client.delete_topic(TopicArn=args.get('topicArn'))
        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return 'The Topic has been deleted'

    except Exception as e:
        return raise_error(e)


def test_function(aws_client):
    try:
        client = aws_client.aws_session(service='sns')
        response = client.list_topics()
        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return "ok"
    except Exception as e:
        return raise_error(e)


def main():

    params = demisto.params()
    aws_default_region = params.get('defaultRegion')
    aws_role_arn = params.get('roleArn')
    aws_role_session_name = params.get('roleSessionName')
    aws_role_session_duration = params.get('sessionDuration')
    aws_role_policy = None
    aws_access_key_id = params.get('access_key')
    aws_secret_access_key = params.get('secret_key')
    verify_certificate = not params.get('insecure', True)
    timeout = params.get('timeout')
    retries = params.get('retries') or 5

    commands = {
        'aws-sns-create-subscription': create_subscription,
        'aws-sns-list-topics': list_topics,
        'aws-sns-list-subscriptions-by-topic': list_subscriptions_by_topic,
        'aws-sns-send-message': send_message,
        'aws-sns-create-topic': create_topic,
        'aws-sns-delete-topic': delete_topic
    }

    try:
        validate_params(aws_default_region, aws_role_arn, aws_role_session_name, aws_access_key_id,
                        aws_secret_access_key)
        aws_client = AWSClient(aws_default_region, aws_role_arn, aws_role_session_name, aws_role_session_duration,
                               aws_role_policy, aws_access_key_id, aws_secret_access_key, verify_certificate, timeout,
                               retries)
        command = demisto.command()
        args = demisto.args()
        demisto.debug('Command being called is {}'.format(command))
        if command == 'test-module':
            return_results(test_function(aws_client))
        elif command in commands:
            client = aws_client.aws_session(
                service='sns',
                region=args.get('region'),
                role_arn=args.get('roleArn'),
                role_session_name=args.get('roleSessionName'),
                role_session_duration=args.get('roleSessionDuration'))
            return_results(commands[command](args, client))
        else:
            raise NotImplementedError('{} is not an existing AWS-SNS command'.format(command))

    except Exception as e:
        return_error("Failed to execute {} command.\nError:\n{}".format(demisto.command(), str(e)))


### GENERATED CODE ###: from AWSApiModule import *  # noqa: E402
# This code was inserted in place of an API module.
register_module_line('AWSApiModule', 'start', __line__(), wrapper=-3)


def validate_params(aws_default_region, aws_role_arn, aws_role_session_name, aws_access_key_id, aws_secret_access_key):
    """
    Validates that the provided parameters are compatible with the appropriate authentication method.
    """
    if not aws_default_region:
        raise DemistoException('You must specify AWS default region.')

    if bool(aws_access_key_id) != bool(aws_secret_access_key):
        raise DemistoException('You must provide Access Key id and Secret key id to configure the instance with '
                               'credentials.')
    if bool(aws_role_arn) != bool(aws_role_session_name):
        raise DemistoException('Role session name is required when using role ARN.')


class AWSClient:

    def __init__(self, aws_default_region, aws_role_arn, aws_role_session_name, aws_role_session_duration,
                 aws_role_policy, aws_access_key_id, aws_secret_access_key, verify_certificate, timeout, retries,
                 aws_session_token=None):

        self.aws_default_region = aws_default_region
        self.aws_role_arn = aws_role_arn
        self.aws_role_session_name = aws_role_session_name
        self.aws_role_session_duration = aws_role_session_duration
        self.aws_role_policy = aws_role_policy
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.aws_session_token = aws_session_token
        self.verify_certificate = verify_certificate

        proxies = handle_proxy(proxy_param_name='proxy', checkbox_default_value=False)
        (read_timeout, connect_timeout) = AWSClient.get_timeout(timeout)
        if int(retries) > 10:
            retries = 10
        self.config = Config(
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries=dict(
                max_attempts=int(retries)
            ),
            proxies=proxies
        )

    def update_config(self):
        command_config = {}
        retries = demisto.getArg('retries')  # Supports retries and timeout parameters on the command execution level
        if retries is not None:
            command_config['retries'] = dict(max_attempts=int(retries))
        timeout = demisto.getArg('timeout')
        if timeout is not None:
            (read_timeout, connect_timeout) = AWSClient.get_timeout(timeout)
            command_config['read_timeout'] = read_timeout
            command_config['connect_timeout'] = connect_timeout
        if retries or timeout:
            demisto.debug('Merging client config settings: {}'.format(command_config))
            self.config = self.config.merge(Config(**command_config))

    def aws_session(self, service, region=None, role_arn=None, role_session_name=None, role_session_duration=None,
                    role_policy=None):
        kwargs = {}

        self.update_config()

        if role_arn and role_session_name is not None:
            kwargs.update({
                'RoleArn': role_arn,
                'RoleSessionName': role_session_name,
            })
        elif self.aws_role_arn and self.aws_role_session_name is not None:
            kwargs.update({
                'RoleArn': self.aws_role_arn,
                'RoleSessionName': self.aws_role_session_name,
            })

        if role_session_duration is not None:
            kwargs.update({'DurationSeconds': int(role_session_duration)})
        elif self.aws_role_session_duration is not None:
            kwargs.update({'DurationSeconds': int(self.aws_role_session_duration)})

        if role_policy is not None:
            kwargs.update({'Policy': role_policy})
        elif self.aws_role_policy is not None:
            kwargs.update({'Policy': self.aws_role_policy})

        if kwargs and not self.aws_access_key_id:  # login with Role ARN

            if not self.aws_access_key_id:
                sts_client = boto3.client('sts', config=self.config, verify=self.verify_certificate,
                                          region_name=self.aws_default_region)
                sts_response = sts_client.assume_role(**kwargs)
                client = boto3.client(
                    service_name=service,
                    region_name=region if region else self.aws_default_region,
                    aws_access_key_id=sts_response['Credentials']['AccessKeyId'],
                    aws_secret_access_key=sts_response['Credentials']['SecretAccessKey'],
                    aws_session_token=sts_response['Credentials']['SessionToken'],
                    verify=self.verify_certificate,
                    config=self.config
                )
        elif self.aws_access_key_id and self.aws_role_arn:  # login with Access Key ID and Role ARN
            sts_client = boto3.client(
                service_name='sts',
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                verify=self.verify_certificate,
                config=self.config
            )
            kwargs.update({
                'RoleArn': self.aws_role_arn,
                'RoleSessionName': self.aws_role_session_name,
            })
            sts_response = sts_client.assume_role(**kwargs)
            client = boto3.client(
                service_name=service,
                region_name=self.aws_default_region,
                aws_access_key_id=sts_response['Credentials']['AccessKeyId'],
                aws_secret_access_key=sts_response['Credentials']['SecretAccessKey'],
                aws_session_token=sts_response['Credentials']['SessionToken'],
                verify=self.verify_certificate,
                config=self.config
            )
        elif self.aws_access_key_id and not self.aws_role_arn:  # login with access key id
            client = boto3.client(
                service_name=service,
                region_name=region if region else self.aws_default_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                verify=self.verify_certificate,
                config=self.config
            )
        elif self.aws_session_token and not self.aws_role_arn:  # login with session token
            client = boto3.client(
                service_name=service,
                region_name=region if region else self.aws_default_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                aws_session_token=self.aws_session_token,
                verify=self.verify_certificate,
                config=self.config
            )
        else:  # login with default permissions, permissions pulled from the ec2 metadata
            client = boto3.client(service_name=service,
                                  region_name=region if region else self.aws_default_region)

        return client

    @staticmethod
    def get_timeout(timeout):
        if not timeout:
            timeout = "60,10"  # default values
        try:

            if isinstance(timeout, int):
                read_timeout = timeout
                connect_timeout = 10

            else:
                timeout_vals = timeout.split(',')
                read_timeout = int(timeout_vals[0])
                # the default connect timeout is 10
                connect_timeout = 10 if len(timeout_vals) == 1 else int(timeout_vals[1])

        except ValueError:
            raise DemistoException("You can specify just the read timeout (for example 60) or also the connect "
                                   "timeout followed after a comma (for example 60,10). If a connect timeout is not "
                                   "specified, a default of 10 second will be used.")
        return read_timeout, connect_timeout


register_module_line('AWSApiModule', 'end', __line__(), wrapper=1)
### END GENERATED CODE ###

if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()

register_module_line('AWS - SNS', 'end', __line__())
