import re

import demistomock as demisto  # noqa: F401
from CommonServerPython import *  # noqa: F401

UserAccountControlFlags = {
    'SCRIPT': 0x0001,
    'ACCOUNTDISABLE': 0x0002,
    'HOMEDIR_REQUIRED': 0x0008,
    'LOCKOUT': 0x0010,
    'PASSWD_NOTREQD': 0x0020,
    'PASSWD_CANT_CHANGE': 0x0040,
    'ENCRYPTED_TEXT_PWD_ALLOWED': 0x0080,
    'TEMP_DUPLICATE_ACCOUNT': 0x0100,
    'NORMAL_ACCOUNT': 0x0200,
    'INTERDOMAIN_TRUST_ACCOUNT': 0x0800,
    'WORKSTATION_TRUST_ACCOUNT': 0x1000,
    'SERVER_TRUST_ACCOUNT': 0x2000,
    'DONT_EXPIRE_PASSWORD': 0x10000,
    'MNS_LOGON_ACCOUNT': 0x20000,
    'SMARTCARD_REQUIRED': 0x40000,
    'TRUSTED_FOR_DELEGATION': 0x80000,
    'NOT_DELEGATED': 0x100000,
    'USE_DES_KEY_ONLY': 0x200000,
    'DONT_REQ_PREAUTH': 0x400000,
    'PASSWORD_EXPIRED': 0x800000,
    'TRUSTED_TO_AUTH_FOR_DELEGATION': 0x1000000,
    'PARTIAL_SECRETS_ACCOUNT': 0x04000000
}

limit = 20
if demisto.get(demisto.args(), 'limit'):
    limit = demisto.args()['limit']


def escapeSpecialCharacters(s):
    return re.sub(r'([\()])', lambda r: '\\' + r.group(), s)


def createAccountEntities(t, attrs):
    accounts = []
    for l in t:
        account = {}
        account['Type'] = 'AD'
        account['ID'] = demisto.get(l, 'dn')
        account['Email'] = {'Address': demisto.get(l, 'mail')}
        account['Username'] = demisto.get(l, 'samAccountName')
        account['DisplayName'] = demisto.get(l, 'displayName')
        account['Manager'] = demisto.get(l, 'manager')
        account['Groups'] = demisto.get(l, 'memberOf').split('<br>') if demisto.get(l, 'memberOf') else ''
        for attr in set(argToList(attrs)) - set(['dn', 'mail', 'name', 'displayName', 'memberOf']):
            account[attr.title()] = demisto.get(l, attr)
        accounts.append(account)

    return accounts


def prettifyDateTimeADFields(resAD):
    try:
        for m in resAD:
            if isError(m):
                continue
            m['ContentsFormat'] = formats['table']
            for f in ['lastlogon', 'lastlogoff', 'pwdLastSet', 'badPasswordTime', 'lastLogonTimestamp']:
                if f not in m['Contents'][0]:
                    continue
                if m['Contents'][0][f] == "0":
                    m['Contents'][0][f] = "N/A"
                else:
                    try:
                        m['Contents'][0][f] = FormatADTimestamp(m['Contents'][0][f]
)
                    except:
                        pass  # Could not prettify timestamp - return as is
            for f in ['whenChanged', 'whenCreated']:
                try:
                    m['Contents'][0][f] = PrettifyCompactedTimestamp(m['Contents'][0][f]
)
                except:
                    pass  # Could not prettify timestamp - return as is
        return resAD
    except Exception as ex:
        return {'Type': entryTypes['error'], 'ContentsFormat': formats['text'],
'Contents': 'Error occurred while parsing output from ad command. Exception info: ' + str(ex) + '\nInvalid output:\n' + str(resAD)}


def translateUserAccountControl(resAD, userAccountControlOut):
    try:
        for m in resAD:
            if isError(m) or not demisto.get(m, 'Contents') or not isinstance(m['Contents'],
list):
                continue
            if 'UserAccountControl' not in m['Contents'][0] or m['Contents'][0]['UserAccountControl']


== "":
                continue
            if userAccountControlOut:
                accountControlFlags = []
                for flag, mask in UserAccountControlFlags.iteritems():
                    if int(m['Contents'][0]['UserAccountControl'],10) & mask !=
0:
                        accountControlFlags.append(flag)
                m['Contents'][0]['UserAccountControl'] = ', '.join(accountControlFlags)
            else:
                m['Contents'][0]['ACCOUNTDISABLE'] = int(m['Contents'][0]['UserAccountControl'],10)
& 2 != 0
        return resAD
    except Exception as ex:
        return { 'Type' : entryTypes['error'], 'ContentsFormat' : formats['text'],
'Contents' : 'Error occurred while parsing output from ad command. Exception info: ' + str(ex) + '\nInvalid output:\n' + str( resAD ) }
def listAll(attrs, using, userAccountControlOut):
    args = {}
    args['filter'] = "(objectClass=User)"
    args['attributes'] = attrs
    args['size-limit'] = limit
    args['using-brand'] = 'activedir'
    if using:
        args['using'] = using
    resAD = getADSearchResp(args)
    if isError(resAD[0]) or isinstance(demisto.get(resAD[0],'Contents'), str) or
isinstance(demisto.get(resAD[0],'Contents'), unicode):
        return resAD
    else:
        resAD = prettifyDateTimeADFields(resAD)
        resAD = translateUserAccountControl(resAD, userAccountControlOut)
        return resAD

def getGroups(userDN):
    queryValue = escapeSpecialCharacters(userDN)
    group_attrs = 'name'
    filterstr = r"(&(member{0}=".format(':1.2.840.113556.1.4.1941:') + queryValue
+ ")(objectcategory=group))"
    args = {
        'filter' : filterstr,
        'attributes' : group_attrs,
        'size-limit' : limit,
        'using-brand' : 'activedir'
    }
    group_resp = getADSearchResp(args)
    if isError(group_resp[0]):
        return group_resp
    try:
        data = demisto.get(group_resp[0],'Contents')
        data = data if isinstance(data, list) else [data]
        memberOf = ",".join([demisto.get(k,'dn') for k in data])
        return memberOf
    except Exception as e:
        return ""


def queryBuilder(queryType,queryValue,attrs,nested,using, userAccountControlOut):
    args = {}
    args['size-limit'] = limit
    args['using-brand'] = 'activedir'
    if using:
        args['using'] = using
    filterstr = r"(&(objectClass=User)({0}={1}))".format(queryType, queryValue)
    args['filter'] = filterstr
    args['attributes'] = attrs
    resp = getADSearchResp(args)
    if isError(resp) or isinstance(demisto.get(resp[0],'Contents'), str) or isinstance(demisto.get(resp[0],'Contents'),
unicode):
        return resp
    if nested:
        for index,user in enumerate(resp[0]['Contents']):
            memberOf = getGroups(user["dn"])
            if memberOf:
                resp[0]['Contents'][index]['memberOf'] = memberOf

    resp = prettifyDateTimeADFields(resp)
    resp = translateUserAccountControl(resp, userAccountControlOut)
    return resp

def getADSearchResp(args):
    try:
        return demisto.executeCommand( 'ad-search', args )
    except Exception as e:
        if 'Unsupported Command' in str(e):
            return_error('No instances of "Active Directory Query" are configured.\nIf
you are trying to run "ADGetUser" with "Active Directory Query V2", please use the aquivilant command "ad-get-user" instead.')
            raise e

attrs = 'dn,name,displayName,memberOf,mail,samAccountName,manager,UserAccountControl,ACCOUNTDISABLE,provider'
queryValue, queryType = "",""
headers = argToList(demisto.get(demisto.args(), 'headers'))
userAccountControlOut = False

nestedSearch = True if demisto.get(demisto.args(), 'nestedSearch') == 'true' else False

if demisto.get(demisto.args(), 'attributes'):
    attrs += "," + demisto.args()['attributes']
if demisto.get(demisto.args(), 'userAccountControlOut'):
    userAccountControlOut = demisto.args()['userAccountControlOut'] == 'true'

if demisto.get(demisto.args(), 'dn'):
    queryValue = demisto.args()['dn']
    queryType = "distinguishedName"
elif demisto.get(demisto.args(), 'name'):
    queryValue = demisto.args()['name']
    queryType = "name"
elif demisto.get(demisto.args(), 'username'):
    queryValue = demisto.args()['username']
    queryType = "samAccountName"
elif demisto.get(demisto.args(), 'email'):
    queryValue = demisto.args()['email']
    queryType = "mail"
elif demisto.get(demisto.args(), 'customFieldType'):
    if not demisto.get(demisto.args(), 'customFieldData'):
        demisto.results({ 'Type' : entryTypes['error'], 'ContentsFormat' : formats['text'],
'' : 'To do custom search, both "customFieldType" and "customFieldData" should be provided' })
    else:
        queryValue = demisto.args()['customFieldData']
        queryType = demisto.args()['customFieldType']
resp = None
if queryValue and queryType:
    resp = queryBuilder(queryType,escapeSpecialCharacters(queryValue),attrs,nestedSearch,demisto.get(demisto.args(),'using'),
userAccountControlOut) else:
    resp = listAll(attrs, demisto.get(demisto.args(),'using'), userAccountControlOut)

if isError(resp):
    demisto.results(resp)
else:
    found = False
    for response in resp:
        context = {}
        data = demisto.get(response,'Contents')
        if isinstance(data, str) or isinstance(data, unicode) :
            if data == 'No results':
                continue
            found = True
            md = data
        else:
            data = data if isinstance(data, list) else [data]
            found = True
            md = tableToMarkdown("Active Directory User", data, headers)
            context['Account(val.Email && val.Email === obj.Email || val.ID && val.ID
=== obj.ID || val.Username && val.Username === obj.Username)'] = createAccountEntities(data,attrs)
            if len(data) > 0 and demisto.get(data[0], 'name'):
                context['DBotScore'] = {'Indicator': data[0]['samAccountName'],
'Type': 'username', 'Vendor': 'AD', 'Score': 0, 'isTypedIndicator': True}
        demisto.results({'Type' : entryTypes['note'],
                        'Contents': data,
                        'ContentsFormat' : formats['json'],
                        'HumanReadable': md,
                        'ReadableContentsFormat' : formats['markdown'],
                        'EntryContext' : context})
    if not found:
        demisto.results({'Type' : entryTypes['note'],
                        'Contents': resp,
                        'ContentsFormat' : formats['json'],
                        'HumanReadable': 'No results found for user',
                        'ReadableContentsFormat' : formats['markdown'],
                        'EntryContext' : {}})
