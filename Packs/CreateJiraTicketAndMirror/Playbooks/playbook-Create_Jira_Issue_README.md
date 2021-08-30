Create Jira issue allows you to open new tickets as a task from a parent playbook.
When creating the ticket, you can decide to update based on on the ticket's state, which will wait for the ticket to resolve or close with StatePolling. 
Alternatively, you can select to mirror the Jira issue and incident fields.  To apply either of these options, set the SyncTicket value in the playbook inputs to one of the following options: 
1. StatePolling
2. Mirror
3. Leave Blank to use none.

## Dependencies
This playbook uses the following sub-playbooks, integrations, and scripts.

### Sub-playbooks
* Mirror Jira Ticket
* Jira Ticket State Polling

### Integrations
This playbook does not use any integrations.

### Scripts
This playbook does not use any scripts.

### Commands
* jira-create-issue
* jira-get-issue

## Playbook Inputs
---

| **Name** | **Description** | **Default Value** | **Required** |
| --- | --- | --- | --- |
| Summary | Set a short description of the ticket. |  | Optional |
| Description | Set the impact for the new ticket. Leave empty for Jira default impact. |  | Optional |
| Attachment | Set the urgency of the new ticket. Leave empty for Jira default urgency. |  | Optional |
| ProjectKey | Jira Project Key |  | Optional |
| IssueTypeName | TaskName | Task | Optional |
| SyncTicket | Set the value of the desired sync method with Jira Issue. you can choose one of three options:<br/>1. StatePolling<br/>2. Mirror <br/>3. Blank for none <br/><br/>GenericPolling polls for the state of the ticket and runs until the ticket state is either resolved or closed. <br/><br/>Mirror - You can use the Mirror option to perform a full sync with the Jira Ticket. The ticket data is synced automatically between Jira and Cortex xSOAR with the Jira mirror feature.<br/>If this option is selected, FieldPolling is true by default.  | Mirror | Optional |
| PollingInterval | Set interval time for the polling to run<br/>\(In minutes\) |  | Optional |
| PollingTimeout | Set the amount of time to poll the status of the ticket before declaring a timeout and resuming the playbook.<br/>\(In minutes\) |  | Optional |
| AdditionalPollingCommandName | In this use case, Additional polling commands are relevant when using StatePolling, and there is more than one Jira instance. It will specify the polling command to use a specific instance to run on. <br/>If so, please add "Using" to the value. <br/>The playbook will then take the instance name as the instance to use.  |  | Optional |
| InstanceName | Set the Jira Instance that will be used for mirroring/running polling commands.<br/> |  | Optional |
| MirrorDirection | Set the mirror direction, should be one of the following: <br/>1. In<br/>2. Out<br/>3. Both | Both | Optional |
| MirrorCommentTags | Set tags for mirror comments and files to Jira. | comment | Optional |
| FieldPolling | Set the value to true or false to determine if the paybook will execute the FieldPolling sub playbook.<br/>It is useful when it is needed to wait for the Jira ticket to be resolved and continue the parent playbook.<br/>FieldPolling will run until the ticket state is either resolved or closed. | true | Optional |

## Playbook Outputs
---
There are no outputs for this playbook.

## Playbook Image
---
![Create Jira Issue](Insert the link to your image here)