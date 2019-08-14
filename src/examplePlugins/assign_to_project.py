# Copyright 2018 Autodesk, Inc.  All rights reserved.
#
# Use of this software is subject to the terms of the Autodesk license agreement
# provided at the time of installation or download, or which otherwise accompanies
# this software in either electronic or hard copy form.
#

# See docs folder for detailed usage info.

import os
import shotgun_api3


def registerCallbacks(reg):
    """
    Register our callbacks.

    :param reg: A Registrar instance provided by the event loop handler.
    """

    # Grab authentication env vars for this plugin. Install these into the env
    # if they don't already exist.
    server = os.environ["SG_SERVER"]
    script_name = os.environ["SGDAEMON_ASSIGNTOPROJECT_NAME"]
    script_key = os.environ["SGDAEMON_ASSIGNTOPROJECT_KEY"]

    # Grab an sg connection for the validator.
    sg = shotgun_api3.Shotgun(server, script_name=script_name, api_key=script_key)

    # Bail if our validator fails.
    if not is_valid(sg, reg.logger):
        reg.logger.warning("Plugin is not valid, will not register callback.")
        return

    # Register our callback with the Shotgun_%s_Change event and tell the logger
    # about it.
    reg.registerCallback(
        script_name,
        script_key,
        assign_to_project,
        {"Shotgun_Task_Change": "task_assignees"},
        None,
    )
    reg.logger.debug("Registered callback.")


def is_valid(sg, logger):
    """
    Validate our args.

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :returns: True if plugin is valid, None if not.
    """

    # Make sure we have a valid sg connection.
    try:
        sg.find_one("Project", [])
    except Exception as e:
        logger.warning(e)
        return

    return True


def assign_to_project(sg, logger, event, args):
    """
    Assigns a HumanUser to a Project if that HumanUser is assigned to a Task
    which belongs to a Project s/he isn't already assigned to.

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :param event: A Shotgun EventLogEntry entity dictionary.
    :param args: Any additional misc arguments passed through this plugin.
    """

    # Make some vars for convenience.
    event_project = event.get("project")
    task_assignees = event.get("meta", {}).get("added")

    # Bail if we don't have the info we need.
    if not event_project or not task_assignees:
        return

    # Gather a list of HumanUsers, whether they're assigned directly to the Task
    # or via a Group. Note that Client Users can not be assigned to a Task or
    # added to a Group.
    users = []
    for task_assignee in task_assignees:
        if task_assignee["type"] == "HumanUser":
            users.append(task_assignee)
        elif task_assignee["type"] == "Group":
            group = sg.find_one(
                "Group",
                [["id", "is", task_assignee["id"]]],
                ["users"],
            )
            for user in group["users"]:
                if user["type"] == "HumanUser":
                    users.append(user)

    # Init our batch data list.
    batch_data = []

    # Loop through all added users.
    for user in users:

        # Grab the user's assigned Projects.
        user = sg.find_one(
            "HumanUser",
            [["id", "is", user["id"]]],
            ["projects"],
        )

        # Check to see if the user is assigned to the Project.
        assigned = False
        for project in user["projects"]:
            if project["id"] == event_project["id"]:
                assigned = True

        # Assign the user to the Project if s/he isn't already assigned.
        if not assigned:
            batch_data.append(
                {
                    "request_type": "update",
                    "entity_type": "HumanUser",
                    "entity_id": user["id"],
                    "data": {
                        "projects": user["projects"] + [event_project],
                    }
                }
            )
            logger.info(
                "Going to add HumanHuser with id %s to Project with id %s." % (
                    user["id"],
                    event_project["id"]
                )
            )

    # And now update all our HumanUser records.
    if batch_data:
        sg.batch(batch_data)
        logger.info("Completed batch update.")
