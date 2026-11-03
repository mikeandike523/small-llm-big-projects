"""Approval policies for automation-triggered turns (heartbeat, email).

These layer on top of the session's normal approval mode: they decide what
happens to a tool call that *still* needs approval when no human started the
subturn.
"""

from __future__ import annotations

AUTOMATION_APPROVAL_POLICY_WAIT_FOR_HUMAN = "wait-for-human"
AUTOMATION_APPROVAL_POLICY_FORCE_FAIL = "force-fail"
AUTOMATION_APPROVAL_POLICY_FORCE_APPROVE = "force-approve"

AUTOMATION_APPROVAL_POLICIES = [
    AUTOMATION_APPROVAL_POLICY_WAIT_FOR_HUMAN,
    AUTOMATION_APPROVAL_POLICY_FORCE_FAIL,
    AUTOMATION_APPROVAL_POLICY_FORCE_APPROVE,
]

# How an automation-triggered message is admitted: the same choices as the
# chat footer's "Follow up behavior" (auto-detect / force-follow-up /
# force-new-task), passed to new_user_message as followup_behavior.
AUTOMATION_FOLLOWUP_AUTO = "auto"
AUTOMATION_FOLLOWUP_FORCE_FOLLOW_UP = "follow-up"
AUTOMATION_FOLLOWUP_FORCE_NEW_TASK = "new-task"

AUTOMATION_FOLLOWUP_BEHAVIORS = [
    AUTOMATION_FOLLOWUP_AUTO,
    AUTOMATION_FOLLOWUP_FORCE_FOLLOW_UP,
    AUTOMATION_FOLLOWUP_FORCE_NEW_TASK,
]
